"""OpenRouter over the chat-completions wire shape, mapped to and from domain values (anti-corruption layer).

Requests carry the endpoint's provider routing, and reasoning stays off unless the sampling asks for it.
"""

import asyncio
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

import httpx
from pydantic import JsonValue, SecretStr

from compass_bench.adapters.transport.errors import classify_exception, classify_status, retry_after_seconds
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import ReasoningEffort
from compass_bench.domain.ledger import (
    AttemptResultKind,
    Completed,
    FinishReason,
    Reply,
    TransportError,
    TransportFailed,
    Usage,
)
from compass_bench.ports.transport import CompletionRequest, Exchange

# 3: the reply carries the response id, the provider's timestamp, the system fingerprint, and the native finish
NORMALIZER_VERSION: Final = 3
CHAT_COMPLETIONS_PATH: Final = "/chat/completions"
REPLY_SCHEMA_NAME: Final = "rating"
FINISH_REASONS: Final[Mapping[str, FinishReason]] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
    "error": FinishReason.HOST_ERROR,
}
# a failure message is kept short: the raw body holds the whole response
MESSAGE_LIMIT: Final = 500
UNSTORABLE_CHARACTER: Final = re.compile("[\x00\ud800-\udfff]")
REPLACEMENT_CHARACTER: Final = "�"


def reasoning_setting(effort: ReasoningEffort) -> dict[str, JsonValue]:
    match effort:
        case ReasoningEffort.OFF:
            return {"enabled": False}
        case ReasoningEffort.LOW | ReasoningEffort.MEDIUM | ReasoningEffort.HIGH:
            return {"effort": effort.value}


def chat_messages(request: CompletionRequest) -> list[JsonValue]:
    """The system prompt, when there is one, then the prompt's messages."""
    system = request.prompt.system
    head: list[JsonValue] = [] if system is None else [{"role": "system", "content": system}]
    return head + [{"role": message.role.value, "content": message.content} for message in request.prompt.messages]


def chat_payload(request: CompletionRequest) -> dict[str, JsonValue]:
    sampling = request.sampling
    payload: dict[str, JsonValue] = {
        "model": request.model,
        "messages": chat_messages(request),
        "temperature": sampling.temperature,
        "max_tokens": sampling.max_tokens,
        "reasoning": reasoning_setting(sampling.reasoning),
        "usage": {"include": True},
    }
    if sampling.top_p is not None:
        payload["top_p"] = sampling.top_p
    if request.reply_schema is not None:
        reply_schema: dict[str, JsonValue] = dict(request.reply_schema)
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": REPLY_SCHEMA_NAME, "strict": True, "schema": reply_schema},
        }
    return payload


def finish_reason(raw: str | None) -> FinishReason:
    return FINISH_REASONS.get(raw, FinishReason.UNKNOWN) if raw is not None else FinishReason.UNKNOWN


def count(section: JsonValue, key: str) -> int:
    """A token count from a usage section; an absent or malformed count is 0."""
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def reported_cost(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def usage(body: Mapping[str, JsonValue]) -> Usage:
    section = body.get("usage")
    details = section if isinstance(section, dict) else {}
    return Usage(
        prompt_tokens=count(details, "prompt_tokens"),
        completion_tokens=count(details, "completion_tokens"),
        reasoning_tokens=count(details.get("completion_tokens_details"), "reasoning_tokens"),
        cached_tokens=count(details.get("prompt_tokens_details"), "cached_tokens"),
        cost_usd=reported_cost(details.get("cost")),
    )


def storable(text: str) -> str:
    """The text with each NUL and lone surrogate replaced by U+FFFD, since Postgres text and jsonb refuse them.

    The raw body keeps the bytes as received."""
    return UNSTORABLE_CHARACTER.sub(REPLACEMENT_CHARACTER, text)


def failed(error: TransportError, http_status: int | None, message: str) -> TransportFailed:
    short = storable(message[:MESSAGE_LIMIT])
    return TransportFailed(kind=AttemptResultKind.FAILED, error=error, http_status=http_status, message=short)


def error_message(body: JsonValue) -> str:
    """The `error.message` OpenRouter sends, else the body itself."""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else str(body)


def text_or_none(value: JsonValue) -> str | None:
    return storable(value) if isinstance(value, str) else None


def timestamp_or_none(value: JsonValue) -> datetime | None:
    """A Unix timestamp as an aware datetime; anything else, a bool included, is None."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return datetime.fromtimestamp(value, UTC)


def normalize(body: JsonValue) -> Completed | TransportFailed:
    """A 2xx body without a usable choice is a failure; reasoning text is kept, not discarded.

    Content missing after a cut at max_tokens or a host error is an empty reply, so its finish decides the outcome."""
    if not isinstance(body, dict):
        return failed(TransportError.MALFORMED_BODY, None, "the response body is not a JSON object")
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        status = code if isinstance(code, int) and not isinstance(code, bool) else None
        kind = classify_status(status, body) if status is not None else TransportError.SERVER_ERROR
        return failed(kind, status, error_message(body))
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return failed(TransportError.MALFORMED_BODY, None, "the response carries no choice")
    choice = choices[0]
    message = choice.get("message")
    fields = message if isinstance(message, dict) else {}
    finish = finish_reason(text_or_none(choice.get("finish_reason")))
    text = text_or_none(fields.get("content"))
    if text is None and finish not in {FinishReason.LENGTH, FinishReason.HOST_ERROR}:
        return failed(TransportError.NO_CONTENT, None, "the choice carries no message content")
    reply = Reply(
        text=text or "",
        reasoning=text_or_none(fields.get("reasoning")),
        finish=finish,
        usage=usage(body),
        served_model=text_or_none(body.get("model")),
        served_provider=text_or_none(body.get("provider")),
        response_id=text_or_none(body.get("id")),
        created_at=timestamp_or_none(body.get("created")),
        system_fingerprint=text_or_none(body.get("system_fingerprint")),
        native_finish_reason=text_or_none(choice.get("native_finish_reason")),
    )
    return Completed(kind=AttemptResultKind.COMPLETED, reply=reply)


def failed_exchange(error: TransportError, message: str) -> Exchange:
    """A request that got no response, so there is no body to keep."""
    result = failed(error, None, message)
    return Exchange(result=result, raw_body=None, normalizer_version=NORMALIZER_VERSION, retry_after_seconds=None)


def response_body(response: httpx.Response) -> JsonValue:
    """The body as JSON for reading, or its text when it is not JSON; the ledger keeps the bytes themselves."""
    try:
        parsed: JsonValue = response.json()
    except ValueError:
        return response.text
    return parsed


class OpenRouterTransport:
    def __init__(self, settings: EndpointSettings, api_key: SecretStr, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.api_key = api_key
        self.client = client
        return

    def payload(self, request: CompletionRequest) -> dict[str, JsonValue]:
        """The chat payload with the endpoint's routing; an empty order or precision list lets OpenRouter pick."""
        routing: dict[str, JsonValue] = {
            "allow_fallbacks": self.settings.allow_fallbacks,
            "require_parameters": self.settings.require_parameters,
        }
        if self.settings.provider_order:
            routing["order"] = list(self.settings.provider_order)
        if self.settings.quantizations:
            routing["quantizations"] = list(self.settings.quantizations)
        return {**chat_payload(request), "provider": routing}

    async def send(self, payload: dict[str, JsonValue]) -> Exchange:
        """Never raises for a transport failure; that is a TransportFailed result.

        timeout_seconds bounds the whole request; httpx's own timeout bounds each connect, write, and read."""
        url = self.settings.base_url.rstrip("/") + CHAT_COMPLETIONS_PATH
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        timeout = self.settings.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                response = await self.client.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as error:
            return failed_exchange(classify_exception(error), str(error) or type(error).__name__)
        except TimeoutError:
            return failed_exchange(TransportError.TIMEOUT, f"no complete response within {timeout} seconds")
        body = response_body(response)
        if response.is_success:
            outcome = normalize(body)
        else:
            outcome = failed(classify_status(response.status_code, body), response.status_code, error_message(body))
        return Exchange(
            result=outcome,
            raw_body=response.content,
            normalizer_version=NORMALIZER_VERSION,
            retry_after_seconds=retry_after_seconds(response.headers),
        )
