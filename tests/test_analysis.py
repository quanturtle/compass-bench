from datetime import timedelta

from compass_bench.domain.analysis import (
    REVIEW_AFTER_DAYS,
    model_fingerprints,
    model_hosts,
    model_served,
    model_usage,
    outcome_counts,
    reply_span,
    review_after,
)
from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.ledger import TransportError
from compass_bench.domain.outcome import LossReason, Lost, Replied, TrialOutcomeKind
from compass_bench.domain.reading.reading import FormatFailureKind
from tests.builders.analysis import pending_record, rated_record, record_of
from tests.builders.ledger import RECEIVED_AT, failed_entry, orphaned_entry, priced_entry, replied_entry


def test_outcome_counts_list_every_failure_and_loss_kind() -> None:
    lost = Lost(kind=TrialOutcomeKind.LOST, loss=LossReason.REQUEST_REJECTED)
    records = (
        rated_record("model", "x-00", Polarity.POSITIVE, 4),
        pending_record("model", "x-00", Polarity.NEGATIVE),
        record_of("model", "y-00", Polarity.POSITIVE, lost),
    )

    counts = outcome_counts(records)

    assert (counts.answered, counts.hedged, counts.declined, counts.pending) == (1, 0, 0, 1)
    assert counts.format_failed == {kind: 0 for kind in FormatFailureKind}
    assert counts.lost == {reason: int(reason is LossReason.REQUEST_REJECTED) for reason in LossReason}


def test_hosts_count_replied_trials_per_upstream_host_and_an_unreported_host_as_unknown() -> None:
    reading = rated_record("model", "x-00", Polarity.POSITIVE, 4).outcome
    assert isinstance(reading, Replied)
    served = Replied(
        kind=TrialOutcomeKind.REPLIED,
        reading=reading.reading,
        host="Upstream",
        served_model="vendor/model-2026-01",
        fingerprint="fp_1",
    )
    records = (
        record_of("model", "x-00", Polarity.POSITIVE, served),
        record_of("model", "x-01", Polarity.POSITIVE, served),
        rated_record("model", "x-02", Polarity.POSITIVE, 4),
        pending_record("model", "x-03", Polarity.POSITIVE),
    )

    assert model_hosts(records) == {"Upstream": 2, "unknown": 1}
    assert model_served(records) == {"vendor/model-2026-01": 2, "unknown": 1}
    assert model_fingerprints(records) == {"fp_1": 2, "unknown": 1}


def test_usage_counts_retries_and_sums_only_reported_costs() -> None:
    entries = (
        failed_entry(0, TransportError.TIMEOUT),
        priced_entry(1, "4", cost_usd=0.002),
        orphaned_entry(2),
        replied_entry(3, "4"),
    )

    usage = model_usage(entries)

    assert (usage.attempts, usage.retries, usage.cost_usd, usage.unpriced_attempts) == (4, 3, 0.002, 3)
    assert usage.prompt_tokens == 200
    assert (usage.completed, usage.reasoning_replies) == (2, 0)


def test_the_reply_span_runs_from_the_first_completed_reply_to_the_last_and_is_empty_without_one() -> None:
    later = replied_entry(1, "4").model_copy(update={"received_at": RECEIVED_AT + timedelta(minutes=3)})

    assert reply_span((replied_entry(0, "4"), later, failed_entry(2, TransportError.TIMEOUT))) == (
        RECEIVED_AT,
        later.received_at,
    )
    assert reply_span((failed_entry(0, TransportError.TIMEOUT), orphaned_entry(1))) == (None, None)


def test_a_position_is_due_a_re_check_a_fixed_number_of_days_after_its_last_reply() -> None:
    assert review_after(RECEIVED_AT) == RECEIVED_AT + timedelta(days=REVIEW_AFTER_DAYS)
    assert review_after(None) is None
