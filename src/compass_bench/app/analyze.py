"""Derive a run's report under the current version."""

from compass_bench.contract.v2 import ReportDocument, report_document
from compass_bench.domain.analysis import analyze
from compass_bench.domain.ids import RunId
from compass_bench.ports.ledger_store import LedgerStore


async def analyze_run(run: RunId, ledger: LedgerStore) -> ReportDocument:
    """Load the run and its ledger, analyze, and build the ReportDocument.

    The document is derived on every call and stored nowhere; the ledger is its only source."""
    planned = await ledger.load_run(run)
    endpoints = await ledger.load_endpoints(run)
    entries = await ledger.load_entries(run)
    return report_document(planned, endpoints, analyze(planned.trials, entries, planned.questionnaire, planned.spec))
