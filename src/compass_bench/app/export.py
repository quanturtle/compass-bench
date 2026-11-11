"""Published report documents, keyed by export file name."""

from collections.abc import Sequence

from pydantic import JsonValue

from compass_bench.app.analyze import analyze_run
from compass_bench.contract.v2 import ReportDocument
from compass_bench.domain.ids import RunId
from compass_bench.ports.ledger_store import LedgerStore


def export_name(document: ReportDocument) -> str:
    """`<run id>.json`, so exporting a run again replaces its document."""
    return f"{document.run.run_id}.json"


async def export_reports(runs: Sequence[RunId], ledger: LedgerStore) -> dict[str, JsonValue]:
    """Each run's document from analyze_run, under its export file name; cli.py writes them.

    Every run is analyzed before anything is written, so an unknown run leaves the directory untouched."""
    documents = [await analyze_run(run, ledger) for run in runs]
    return {export_name(document): document.model_dump(mode="json") for document in documents}
