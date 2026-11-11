"""OpenRouter transports over a mocked HTTP layer, and the bodies they answer with."""

import asyncio
from collections.abc import Callable
from typing import Final

import httpx
from pydantic import JsonValue, SecretStr

from compass_bench.adapters.transport.openrouter import OpenRouterTransport
from compass_bench.domain.design.experiment import ReasoningEffort, Sampling
from compass_bench.ports.transport import CompletionRequest
from tests.builders.ledger import PROMPT
from tests.builders.stores import ENDPOINT

REPLY_BODY: Final[dict[str, JsonValue]] = {
    "id": "gen-1",
    "model": "vendor/model",
    "provider": "Upstream",
    "created": 1767225600,
    "system_fingerprint": "fp_123",
    "choices": [
        {
            "finish_reason": "stop",
            "native_finish_reason": "end_turn",
            "message": {"role": "assistant", "content": "4", "reasoning": "hmm"},
        }
    ],
    "usage": {
        "prompt_tokens": 120,
        "completion_tokens": 3,
        "completion_tokens_details": {"reasoning_tokens": 2},
        "cost": 0.000015,
    },
}


def mocked_transport(handler: Callable[[httpx.Request], httpx.Response]) -> OpenRouterTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterTransport(ENDPOINT, SecretStr("test-key"), client)


async def answer_late(request: httpx.Request) -> httpx.Response:
    """The reply body, after a second."""
    await asyncio.sleep(1.0)
    return httpx.Response(200, json=REPLY_BODY)


def stalled_transport(timeout_seconds: float) -> OpenRouterTransport:
    """A transport whose endpoint times out after `timeout_seconds`, over a server that answers after a second."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(answer_late))
    return OpenRouterTransport(
        ENDPOINT.model_copy(update={"timeout_seconds": timeout_seconds}), SecretStr("key"), client
    )


def filtered_transport(quantizations: tuple[str, ...]) -> OpenRouterTransport:
    """A transport whose endpoint filters hosts by precision, over a server that answers at once."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=REPLY_BODY)))
    return OpenRouterTransport(ENDPOINT.model_copy(update={"quantizations": quantizations}), SecretStr("key"), client)


def refuse_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def completion_request(reasoning: ReasoningEffort, reply_schema: dict[str, JsonValue] | None) -> CompletionRequest:
    sampling = Sampling(temperature=0.0, top_p=None, max_tokens=8, reasoning=reasoning)
    return CompletionRequest(model="vendor/model", prompt=PROMPT, sampling=sampling, reply_schema=reply_schema)
