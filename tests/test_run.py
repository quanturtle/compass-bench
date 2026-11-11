from compass_bench.domain.ids import EndpointId, TrialKey
from compass_bench.domain.ledger import LedgerEntry, TransportError
from compass_bench.domain.outcome import LossReason, Lost, Pending, TrialOutcomeKind, TrialRecord
from compass_bench.domain.run import ModelProgress, latest_budget, run_progress
from tests.builders.design import build_trial
from tests.builders.ledger import failed_entry, orphaned_entry
from tests.builders.run import RESUMED_AFTER_A_CIRCUIT


def test_progress_counts_trials_and_orphans_and_only_circuits_opened_since_the_resume() -> None:
    lost, waiting = build_trial("lost", "model", 0), build_trial("waiting", "model", 1)
    entries: dict[TrialKey, tuple[LedgerEntry, ...]] = {
        lost.key: (failed_entry(0, TransportError.REQUEST_REJECTED),),
        waiting.key: (orphaned_entry(0),),
    }
    records = (
        TrialRecord(trial=lost, outcome=Lost(kind=TrialOutcomeKind.LOST, loss=LossReason.REQUEST_REJECTED)),
        TrialRecord(trial=waiting, outcome=Pending(kind=TrialOutcomeKind.PENDING, attempts=1)),
    )

    progress = run_progress(records, entries, RESUMED_AFTER_A_CIRCUIT)

    assert progress.models == (ModelProgress(model=lost.model, finished=1, pending=1),)
    assert (progress.orphaned, progress.open_circuits) == (1, (EndpointId("second"),))


def test_the_latest_budget_is_the_resumed_one() -> None:
    assert latest_budget(RESUMED_AFTER_A_CIRCUIT) == 2.0
