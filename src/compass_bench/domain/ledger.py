"""Attempts and their results: the domain view of the append-only ledger."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.ids import TrialKey
from compass_bench.domain.value import Value


class Attempt(Value):
    """Its key is attempt_id(trial, seq); seq 0 asks and every later seq retries the one before it.

    `reserved_usd` is the estimated cost the budget reserved before the send."""

    trial: TrialKey
    seq: int
    prompt: Prompt
    reserved_usd: float


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    HOST_ERROR = "host_error"
    UNKNOWN = "unknown"


class Usage(Value):
    """`cost_usd` is the cost the provider reported, or None when it reported none."""

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    cost_usd: float | None


class Reply(Value):
    """`served_model` and `served_provider` are what the endpoint reported serving; `response_id` is its id for
    the generation, `created_at` the provider's own timestamp for it, `system_fingerprint` the backend
    configuration the provider named, and `native_finish_reason` the finish reason as the host gave it.
    Each is None when the body did not carry it."""

    text: str
    reasoning: str | None
    finish: FinishReason
    usage: Usage
    served_model: str | None
    served_provider: str | None
    response_id: str | None
    created_at: datetime | None
    system_fingerprint: str | None
    native_finish_reason: str | None


class TransportError(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    REQUEST_REJECTED = "request_rejected"
    MODERATION = "moderation"
    UNAUTHORIZED = "unauthorized"
    PAYMENT_REQUIRED = "payment_required"
    MODEL_NOT_FOUND = "model_not_found"
    MALFORMED_BODY = "malformed_body"
    NO_CONTENT = "no_content"


class AttemptResultKind(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class Completed(Value):
    kind: Literal[AttemptResultKind.COMPLETED]
    reply: Reply


class TransportFailed(Value):
    kind: Literal[AttemptResultKind.FAILED]
    error: TransportError
    http_status: int | None
    message: str


type AttemptResult = Annotated[Completed | TransportFailed, Field(discriminator="kind")]


class LedgerEntryKind(StrEnum):
    FINISHED = "finished"
    ORPHANED = "orphaned"


class Finished(Value):
    """`received_at` is when the ledger recorded the result, by the ledger's clock."""

    kind: Literal[LedgerEntryKind.FINISHED]
    attempt: Attempt
    result: AttemptResult
    received_at: datetime


class Orphaned(Value):
    """Sent, with no result recorded: the process stopped while the request was in flight."""

    kind: Literal[LedgerEntryKind.ORPHANED]
    attempt: Attempt


type LedgerEntry = Annotated[Finished | Orphaned, Field(discriminator="kind")]


def opens_circuit(error: TransportError) -> bool:
    """An endpoint-level failure, such as a bad key: it stops the endpoint's trials instead of ending one trial."""
    return error in {TransportError.UNAUTHORIZED, TransportError.PAYMENT_REQUIRED}


def opens_model_circuit(error: TransportError) -> bool:
    """A model-level failure: OpenRouter serves no route for the slug, so only that model's trials stop."""
    return error is TransportError.MODEL_NOT_FOUND


def is_retryable(error: TransportError) -> bool:
    """A failure that says nothing about the request: the trial is retried, and a run of them opens the circuit.

    A transient one, or a response that is no completion at all, as a wrong base_url or a proxy page answers."""
    return error in {
        TransportError.TIMEOUT,
        TransportError.CONNECTION,
        TransportError.RATE_LIMITED,
        TransportError.SERVER_ERROR,
        TransportError.MALFORMED_BODY,
    }
