from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.ledger import TransportError
from compass_bench.domain.outcome import LossReason, Lost, Pending, Replied, TrialOutcomeKind, fold_outcome
from compass_bench.domain.reading.reading import RatingRead
from tests.builders.corpus import BASELINE_CONTEXT
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec
from tests.builders.ledger import failed_entry, orphaned_entry, outage_entry, replied_entry

MODEL = build_model_spec(AnswerType.FREE_TEXT)
DESIGN = build_design(BOTH_FACTORS, repetitions=1)


def test_a_reply_after_a_retry_and_an_orphan_decides_the_outcome() -> None:
    entries = (failed_entry(0, TransportError.TIMEOUT), orphaned_entry(1), replied_entry(2, "4"))

    outcome = fold_outcome(entries, MODEL, BASELINE_CONTEXT, DESIGN)

    assert isinstance(outcome, Replied) and isinstance(outcome.reading, RatingRead) and outcome.reading.canonical == 4


def test_retryable_failures_past_max_retries_lose_the_trial() -> None:
    failures = tuple(failed_entry(seq, TransportError.RATE_LIMITED) for seq in range(DESIGN.max_retries + 1))

    assert fold_outcome(failures[:-1], MODEL, BASELINE_CONTEXT, DESIGN) == Pending(
        kind=TrialOutcomeKind.PENDING, attempts=DESIGN.max_retries
    )
    assert fold_outcome(failures, MODEL, BASELINE_CONTEXT, DESIGN) == Lost(
        kind=TrialOutcomeKind.LOST, loss=LossReason.RETRIES_EXHAUSTED
    )


def test_failures_in_an_outage_use_up_no_retry() -> None:
    outage = tuple(outage_entry(seq, TransportError.TIMEOUT) for seq in range(2 * DESIGN.max_retries))
    counted = tuple(failed_entry(len(outage) + seq, TransportError.TIMEOUT) for seq in range(DESIGN.max_retries + 1))

    assert fold_outcome((*outage, *counted[:-1]), MODEL, BASELINE_CONTEXT, DESIGN) == Pending(
        kind=TrialOutcomeKind.PENDING, attempts=3 * DESIGN.max_retries
    )
    assert fold_outcome((*outage, *counted), MODEL, BASELINE_CONTEXT, DESIGN) == Lost(
        kind=TrialOutcomeKind.LOST, loss=LossReason.RETRIES_EXHAUSTED
    )


def test_unusable_bodies_leave_the_trial_pending_until_its_retries_are_used_up() -> None:
    failures = tuple(failed_entry(seq, TransportError.MALFORMED_BODY) for seq in range(DESIGN.max_retries + 1))

    assert fold_outcome(failures[:1], MODEL, BASELINE_CONTEXT, DESIGN) == Pending(
        kind=TrialOutcomeKind.PENDING, attempts=1
    )
    assert fold_outcome(failures, MODEL, BASELINE_CONTEXT, DESIGN) == Lost(
        kind=TrialOutcomeKind.LOST, loss=LossReason.NO_COMPLETION
    )


def test_an_endpoint_failure_leaves_the_trial_pending() -> None:
    entries = tuple(failed_entry(seq, TransportError.UNAUTHORIZED) for seq in range(DESIGN.max_retries + 2))

    assert isinstance(fold_outcome(entries, MODEL, BASELINE_CONTEXT, DESIGN), Pending)


def test_a_rejected_request_loses_the_trial_at_once() -> None:
    outcome = fold_outcome((failed_entry(0, TransportError.REQUEST_REJECTED),), MODEL, BASELINE_CONTEXT, DESIGN)

    assert outcome == Lost(kind=TrialOutcomeKind.LOST, loss=LossReason.REQUEST_REJECTED)
