import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import JsonValue

from compass_bench.adapters.transport.openrouter import NORMALIZER_VERSION
from compass_bench.domain.design.experiment import ReasoningEffort
from compass_bench.domain.ledger import Completed, FinishReason, TransportError, TransportFailed
from tests.builders.transport import (
    REPLY_BODY,
    completion_request,
    filtered_transport,
    mocked_transport,
    refuse_connection,
    stalled_transport,
)


def test_a_reply_body_becomes_a_completed_reply_with_its_reported_cost() -> None:
    transport = mocked_transport(lambda request: httpx.Response(200, json=REPLY_BODY))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed)
    reply = exchange.result.reply
    assert (reply.text, reply.reasoning, reply.served_provider) == ("4", "hmm", "Upstream")
    assert (reply.usage.prompt_tokens, reply.usage.reasoning_tokens, reply.usage.cost_usd) == (120, 2, 0.000015)
    assert exchange.raw_body is not None and json.loads(exchange.raw_body) == REPLY_BODY
    assert (reply.response_id, reply.system_fingerprint, reply.native_finish_reason) == ("gen-1", "fp_123", "end_turn")
    assert reply.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert exchange.normalizer_version == NORMALIZER_VERSION


def test_a_body_without_provenance_fields_leaves_them_unset() -> None:
    bare = {key: value for key, value in REPLY_BODY.items() if key not in {"id", "created", "system_fingerprint"}}
    transport = mocked_transport(lambda request: httpx.Response(200, json={**bare, "created": True}))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed)
    reply = exchange.result.reply
    assert (reply.response_id, reply.created_at, reply.system_fingerprint) == (None, None, None)


@pytest.mark.parametrize("created", [1767225600000, 1e18, -1e18], ids=["milliseconds", "too late", "too early"])
def test_a_created_outside_the_datetime_range_leaves_the_reply_undated(created: float) -> None:
    body: dict[str, JsonValue] = {**REPLY_BODY, "created": created}
    transport = mocked_transport(lambda request: httpx.Response(200, json=body))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed)
    assert (exchange.result.reply.text, exchange.result.reply.created_at) == ("4", None)


def test_a_reported_cost_too_large_for_a_float_is_no_cost() -> None:
    body: dict[str, JsonValue] = {**REPLY_BODY, "usage": {"prompt_tokens": 120, "cost": 10**400}}
    transport = mocked_transport(lambda request: httpx.Response(200, json=body))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed) and exchange.result.reply.usage.cost_usd is None


def test_a_nul_in_the_reply_is_replaced_in_the_text_and_kept_in_the_raw_body() -> None:
    choice = {"finish_reason": "stop", "message": {"role": "assistant", "content": "4\u0000"}}
    transport = mocked_transport(lambda request: httpx.Response(200, json={**REPLY_BODY, "choices": [choice]}))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed) and exchange.result.reply.text == "4�"
    assert exchange.raw_body is not None and b"\\u0000" in exchange.raw_body


def test_a_host_error_without_content_is_a_reply_that_finished_with_host_error() -> None:
    choice = {"finish_reason": "error", "message": {"role": "assistant", "content": None}}
    transport = mocked_transport(lambda request: httpx.Response(200, json={**REPLY_BODY, "choices": [choice]}))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, Completed) and exchange.result.reply.finish is FinishReason.HOST_ERROR


def test_a_rate_limit_is_a_failed_result_carrying_its_retry_after() -> None:
    body = {"error": {"code": 429, "message": "slow down"}}
    transport = mocked_transport(lambda request: httpx.Response(429, json=body, headers={"Retry-After": "7"}))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert isinstance(exchange.result, TransportFailed)
    assert (exchange.result.error, exchange.result.http_status, exchange.retry_after_seconds) == (
        TransportError.RATE_LIMITED,
        429,
        7.0,
    )


@pytest.mark.parametrize("header", ["inf", "1e999", "nan"])
def test_a_retry_after_that_is_not_a_finite_number_counts_as_absent(header: str) -> None:
    body = {"error": {"code": 429, "message": "slow down"}}
    transport = mocked_transport(lambda request: httpx.Response(429, json=body, headers={"Retry-After": header}))

    exchange = asyncio.run(transport.send({"model": "vendor/model"}))

    assert exchange.retry_after_seconds is None


def test_a_connection_error_is_a_failed_result_not_an_exception() -> None:
    exchange = asyncio.run(mocked_transport(refuse_connection).send({"model": "vendor/model"}))

    assert isinstance(exchange.result, TransportFailed) and exchange.result.error is TransportError.CONNECTION


def test_a_response_slower_than_the_endpoint_timeout_is_a_timeout() -> None:
    exchange = asyncio.run(stalled_transport(timeout_seconds=0.01).send({"model": "vendor/model"}))

    assert isinstance(exchange.result, TransportFailed) and exchange.result.error is TransportError.TIMEOUT


def test_the_payload_turns_reasoning_off_and_carries_the_routing_and_the_reply_schema() -> None:
    transport = mocked_transport(lambda request: httpx.Response(200, json=REPLY_BODY))
    schema: dict[str, JsonValue] = {"type": "object"}

    payload = transport.payload(completion_request(ReasoningEffort.OFF, schema))

    assert payload["reasoning"] == {"enabled": False}
    assert payload["provider"] == {"allow_fallbacks": True, "require_parameters": True}
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "rating", "strict": True, "schema": schema},
    }


def test_the_payload_carries_the_quantization_filter_only_when_the_endpoint_sets_one() -> None:
    payload = filtered_transport(("bf16", "fp16")).payload(completion_request(ReasoningEffort.OFF, None))

    assert payload["provider"] == {
        "allow_fallbacks": True,
        "require_parameters": True,
        "quantizations": ["bf16", "fp16"],
    }
