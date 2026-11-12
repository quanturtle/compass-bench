"""Trial outcomes: a left fold over a trial's attempts in sequence order."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from compass_bench.domain.design.experiment import Design, ModelSpec
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.elicitation.answer_types import answer_type_strategy
from compass_bench.domain.ledger import (
    Completed,
    Finished,
    FinishReason,
    LedgerEntry,
    Orphaned,
    Reply,
    TransportError,
    TransportFailed,
    is_retryable,
    opens_circuit,
    opens_model_circuit,
)
from compass_bench.domain.reading.reading import ReadContext, Reading
from compass_bench.domain.value import Value


class LossReason(StrEnum):
    NO_COMPLETION = "no_completion"
    NO_CONTENT = "no_content"
    HOST_ERROR = "host_error"
    REQUEST_REJECTED = "request_rejected"
    RETRIES_EXHAUSTED = "retries_exhausted"


class TrialOutcomeKind(StrEnum):
    REPLIED = "replied"
    LOST = "lost"
    PENDING = "pending"


class Replied(Value):
    """A reply came back; its reading is a rating, a decline, or a format failure, with the rule that decided it.

    `host` is the upstream provider that served the reply, `served_model` the model string and `fingerprint` the
    backend configuration it reported, each as the endpoint reported it, or None."""

    kind: Literal[TrialOutcomeKind.REPLIED]
    reading: Reading
    host: str | None
    served_model: str | None
    fingerprint: str | None


class Lost(Value):
    kind: Literal[TrialOutcomeKind.LOST]
    loss: LossReason


class Pending(Value):
    kind: Literal[TrialOutcomeKind.PENDING]
    attempts: int


type TrialOutcome = Annotated[Replied | Lost | Pending, Field(discriminator="kind")]


class TrialRecord(Value):
    trial: Trial
    outcome: TrialOutcome


def loss_reason(failure: TransportFailed) -> LossReason:
    """A retryable error loses a trial only once its retries are used up; an endpoint or model error loses none."""
    match failure.error:
        case TransportError.REQUEST_REJECTED | TransportError.MODERATION:
            return LossReason.REQUEST_REJECTED
        case TransportError.NO_CONTENT:
            return LossReason.NO_CONTENT
        case TransportError.MALFORMED_BODY:
            return LossReason.NO_COMPLETION
        case TransportError.TIMEOUT | TransportError.CONNECTION | TransportError.RATE_LIMITED:
            return LossReason.RETRIES_EXHAUSTED
        case TransportError.SERVER_ERROR:
            return LossReason.RETRIES_EXHAUSTED
        case TransportError.UNAUTHORIZED | TransportError.PAYMENT_REQUIRED | TransportError.MODEL_NOT_FOUND:
            raise ValueError(f"{failure.error} opens a circuit and loses no trial")


def fold_outcome(
    entries: Sequence[LedgerEntry],
    model: ModelSpec,
    context: ReadContext,
    design: Design,
) -> TrialOutcome:
    """The first completed reply decides the outcome, read by its model's answer type; nothing re-asks it if unreadable.

    A transport failure loses the trial unless it is retryable with retries left, or `in_outage`, which uses up none."""
    retryable_failures = 0
    for entry in sorted(entries, key=lambda entry: entry.attempt.seq):
        match entry:
            case Orphaned():
                continue
            case Finished(result=TransportFailed(), in_outage=True):
                continue
            case Finished(result=Completed(reply=reply)) if reply.finish is FinishReason.HOST_ERROR:
                return Lost(kind=TrialOutcomeKind.LOST, loss=LossReason.HOST_ERROR)
            case Finished(result=Completed(reply=reply)):
                reading = answer_type_strategy(model.answer_type).read(reply, context)
                return Replied(
                    kind=TrialOutcomeKind.REPLIED,
                    reading=reading,
                    host=reply.served_provider,
                    served_model=reply.served_model,
                    fingerprint=reply.system_fingerprint,
                )
            case Finished(result=TransportFailed(error=error)) if opens_circuit(error) or opens_model_circuit(error):
                continue
            case Finished(result=TransportFailed(error=error) as failure) if is_retryable(error):
                retryable_failures += 1
                if retryable_failures > design.max_retries:
                    return Lost(kind=TrialOutcomeKind.LOST, loss=loss_reason(failure))
            case Finished(result=TransportFailed() as failure):
                return Lost(kind=TrialOutcomeKind.LOST, loss=loss_reason(failure))
    return Pending(kind=TrialOutcomeKind.PENDING, attempts=len(entries))


def first_reply(entries: Sequence[LedgerEntry]) -> Reply | None:
    """The reply fold_outcome reads: the first completed one in seq order, or None when no attempt completed."""
    for entry in sorted(entries, key=lambda entry: entry.attempt.seq):
        match entry:
            case Finished(result=Completed(reply=reply)):
                return reply
            case _:
                continue
    return None


def is_terminal(outcome: TrialOutcome) -> bool:
    match outcome:
        case Replied() | Lost():
            return True
        case Pending():
            return False
