"""Run overviews for `runs list` and `runs show`."""

from compass_bench.domain.analysis import trial_records
from compass_bench.domain.ids import RunId
from compass_bench.domain.run import RunOverview, run_progress
from compass_bench.ports.ledger_store import LedgerStore


async def run_overview(run: RunId, ledger: LedgerStore) -> RunOverview:
    planned = await ledger.load_run(run)
    entries = await ledger.load_entries(run)
    events = await ledger.load_events(run)
    records = trial_records(planned.trials, entries, planned.questionnaire, planned.spec)
    return RunOverview(run=planned.run, progress=run_progress(records, entries, events))


async def run_overviews(ledger: LedgerStore) -> tuple[RunOverview, ...]:
    """Every stored run, oldest first."""
    return tuple([await run_overview(record.run_id, ledger) for record in await ledger.list_runs()])
