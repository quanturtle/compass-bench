"""Model transports. A transport builds the wire payload first, so the ledger records it before sending."""

from collections.abc import Mapping
from typing import Protocol

from pydantic import JsonValue

from compass_bench.domain.design.experiment import Sampling
from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.ledger import AttemptResult
from compass_bench.domain.value import Value


class CompletionRequest(Value):
    model: str
    prompt: Prompt
    sampling: Sampling
    reply_schema: Mapping[str, JsonValue] | None


class Exchange(Value):
    """`raw_body` is the response body's bytes as received, or None when no response arrived.

    `retry_after_seconds` comes from a Retry-After header. The collector reads it; the ledger stores it nowhere."""

    result: AttemptResult
    raw_body: bytes | None
    normalizer_version: int
    retry_after_seconds: float | None


class Transport(Protocol):
    def payload(self, request: CompletionRequest) -> dict[str, JsonValue]: ...

    async def send(self, payload: dict[str, JsonValue]) -> Exchange:
        """Never raises for a transport failure; that is a TransportFailed result."""
        ...
