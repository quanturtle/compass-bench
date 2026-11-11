"""Derive the pooled reports of every run that asked a questionnaire."""

from collections.abc import Mapping, Sequence

from compass_bench.contract.v2 import Endpoints, PooledReportDocument, pooled_report_document
from compass_bench.domain.ids import QuestionnaireHash, RunId
from compass_bench.domain.pooling import PooledAnalysis, pooled_analyses, scale_references
from compass_bench.ports.ledger_store import LedgerStore


async def pooled_reports(questionnaire: QuestionnaireHash, ledger: LedgerStore) -> tuple[PooledReportDocument, ...]:
    """One document per pool of the runs that asked the questionnaire, none when no run did.

    Every document is derived on each call and stored nowhere; raises ModelSettingsDiffer before analyzing a pool."""
    planned = [await ledger.load_run(record.run_id) for record in await ledger.list_runs()]
    asked = [run for run in planned if run.spec.questionnaire == questionnaire]
    runs = [(run, await ledger.load_entries(run.run.run_id)) for run in asked]
    endpoints = {run.run.run_id: await ledger.load_endpoints(run.run.run_id) for run in asked}
    return pooled_documents(pooled_analyses(runs), endpoints)


def pooled_documents(
    analyses: Sequence[PooledAnalysis], endpoints: Mapping[RunId, Endpoints]
) -> tuple[PooledReportDocument, ...]:
    """One document per pool, each forced-choice pool read against its native counterpart among `analyses`.

    `endpoints` are each run's stored settings."""
    references = scale_references(analyses)
    return tuple(
        pooled_report_document(key, members, endpoints, result, reliability, references.get(key, {}))
        for key, members, result, reliability in analyses
    )


def pooled_export_name(document: PooledReportDocument) -> str:
    """`pooled-<pool id>.json`, so writing a pool again replaces its document."""
    return f"pooled-{document.pool}.json"
