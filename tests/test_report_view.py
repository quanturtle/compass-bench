"""Text snapshots of five example reports; the contract document, not this text, is what tests assert on."""

from pathlib import Path
from typing import Final

import pytest

from compass_bench.adapters.terminal.report_view import render_pooled_text, render_text
from compass_bench.contract.examples import example_endpoints, example_runs
from compass_bench.contract.schema import pooled_example_documents
from compass_bench.contract.v2 import report_document
from tests.builders.examples import analyzed_example

SNAPSHOT_DIRECTORY: Final = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize("name", ["asserted", "partial", "preregistered"])
def test_the_text_report_matches_its_snapshot(name: str) -> None:
    planned, _ = example_runs()[name]

    text = render_text(report_document(planned, example_endpoints(), analyzed_example(name)))

    assert text + "\n" == (SNAPSHOT_DIRECTORY / f"{name}.txt").read_text()


@pytest.mark.parametrize("name", ["pooled", "cross-scale-forced_choice"])
def test_the_pooled_text_report_matches_its_snapshot(name: str) -> None:
    text = render_pooled_text(pooled_example_documents()[name])

    assert text + "\n" == (SNAPSHOT_DIRECTORY / f"{name}.txt").read_text()
