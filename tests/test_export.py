import asyncio
from pathlib import Path

import pytest
from pydantic import JsonValue

from compass_bench.adapters.files.export_writer import UnwritableExport, write_document
from compass_bench.app.export import export_reports
from compass_bench.contract.v2 import ReportDocument
from compass_bench.domain.ids import RunId
from tests.builders.examples import store_example
from tests.builders.fakes import FakeLedgerStore


async def exported_documents() -> tuple[RunId, dict[str, JsonValue]]:
    store = FakeLedgerStore()
    run = await store_example(store, "asserted")
    return run, dict(await export_reports([run], store))


def test_an_exported_document_reads_back_as_the_same_report(tmp_path: Path) -> None:
    run, documents = asyncio.run(exported_documents())
    ((name, document),) = documents.items()

    path = write_document(tmp_path / "reports", name, document)

    assert path.name == f"{run}.json"
    assert ReportDocument.model_validate_json(path.read_text()).model_dump(mode="json") == document


def test_an_output_directory_that_is_a_file_is_refused_by_name(tmp_path: Path) -> None:
    occupied = tmp_path / "reports"
    occupied.write_text("")

    with pytest.raises(UnwritableExport, match="reports"):
        write_document(occupied, "run.json", {"version": 1})


def test_writing_a_document_again_replaces_it_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    write_document(tmp_path, "run.json", {"version": 1})
    write_document(tmp_path, "run.json", {"version": 2})

    assert [path.name for path in tmp_path.iterdir()] == ["run.json"]
    assert (tmp_path / "run.json").read_text() == '{\n  "version": 2\n}\n'
