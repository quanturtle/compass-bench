"""The contract's example runs, analyzed or written into a ledger store."""

from compass_bench.contract.examples import example_endpoints, example_runs
from compass_bench.domain.analysis import AnalysisResult, analyze
from compass_bench.domain.ids import RunId, attempt_id
from compass_bench.domain.ledger import Finished
from compass_bench.domain.run import NewRun
from compass_bench.ports.ledger_store import LedgerStore
from compass_bench.ports.transport import Exchange


def analyzed_example(name: str) -> AnalysisResult:
    planned, entries = example_runs()[name]
    return analyze(planned.trials, entries, planned.questionnaire, planned.spec)


async def store_example(store: LedgerStore, name: str) -> RunId:
    """Write the example's run, trials, attempts, and results as collection would."""
    planned, entries = example_runs()[name]
    record = planned.run
    new_run = NewRun(
        run_id=record.run_id,
        experiment=record.experiment,
        nonce=record.nonce,
        code_revision=record.code_revision,
        listings=record.listings,
    )
    await store.create_run(new_run, planned.questionnaire, planned.spec, planned.trials, example_endpoints())
    async with store.lock_run(record.run_id):
        for trial_entries in entries.values():
            for entry in trial_entries:
                await store.record_attempt(entry.attempt, {"model": "example"})
                if isinstance(entry, Finished):
                    exchange = Exchange(
                        result=entry.result, raw_body=None, normalizer_version=2, retry_after_seconds=None
                    )
                    await store.record_result(attempt_id(entry.attempt.trial, entry.attempt.seq), exchange)
    return record.run_id
