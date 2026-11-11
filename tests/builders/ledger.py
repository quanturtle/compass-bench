"""Replies, attempts, and ledger entries."""

from datetime import UTC, datetime
from typing import Final

from compass_bench.domain.elicitation.prompts import Message, Prompt, Role
from compass_bench.domain.ids import TrialKey
from compass_bench.domain.ledger import (
    Attempt,
    AttemptResult,
    AttemptResultKind,
    Completed,
    Finished,
    FinishReason,
    LedgerEntryKind,
    Orphaned,
    Reply,
    TransportError,
    TransportFailed,
    Usage,
)
from compass_bench.ports.transport import Exchange

TRIAL: Final = TrialKey("trial")
PROMPT: Final = Prompt(system=None, messages=(Message(role=Role.USER, content="Rate the statement."),))
RECEIVED_AT: Final = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)


def build_reply(text: str, finish: FinishReason) -> Reply:
    return Reply(
        text=text,
        reasoning=None,
        finish=finish,
        usage=Usage(prompt_tokens=100, completion_tokens=1, reasoning_tokens=0, cached_tokens=0, cost_usd=None),
        served_model=None,
        served_provider=None,
        response_id=None,
        created_at=None,
        system_fingerprint=None,
        native_finish_reason=None,
    )


def attempt_on(trial: TrialKey, seq: int) -> Attempt:
    return Attempt(trial=trial, seq=seq, prompt=PROMPT, reserved_usd=0.001)


def build_attempt(seq: int) -> Attempt:
    return attempt_on(TRIAL, seq)


def replied_result(text: str) -> Completed:
    return Completed(kind=AttemptResultKind.COMPLETED, reply=build_reply(text, FinishReason.STOP))


def priced_result(text: str, cost_usd: float) -> Completed:
    """A reply whose provider reported `cost_usd`."""
    reply = build_reply(text, FinishReason.STOP)
    usage = reply.usage.model_copy(update={"cost_usd": cost_usd})
    return Completed(kind=AttemptResultKind.COMPLETED, reply=reply.model_copy(update={"usage": usage}))


def failed_result(error: TransportError) -> TransportFailed:
    return TransportFailed(kind=AttemptResultKind.FAILED, error=error, http_status=None, message=str(error))


def finished_entry(seq: int, result: AttemptResult) -> Finished:
    return Finished(kind=LedgerEntryKind.FINISHED, attempt=build_attempt(seq), result=result, received_at=RECEIVED_AT)


def replied_entry(seq: int, text: str) -> Finished:
    return finished_entry(seq, replied_result(text))


def priced_entry(seq: int, text: str, cost_usd: float) -> Finished:
    return finished_entry(seq, priced_result(text, cost_usd))


def failed_entry(seq: int, error: TransportError) -> Finished:
    return finished_entry(seq, failed_result(error))


def orphaned_entry(seq: int) -> Orphaned:
    return Orphaned(kind=LedgerEntryKind.ORPHANED, attempt=build_attempt(seq))


def exchange_of(result: AttemptResult) -> Exchange:
    return Exchange(result=result, raw_body=b'{"id": "generation"}', normalizer_version=1, retry_after_seconds=None)
