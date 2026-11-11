"""The checked-in schema/ is what scripts/generate_schema.py writes, and its examples validate against it."""

import json
from pathlib import Path
from typing import Final

import pytest
from jsonschema import Draft202012Validator

from compass_bench.contract.schema import (
    POOLED_SCHEMA_FILE,
    SCHEMA_FILE,
    example_documents,
    example_json,
    pooled_example_documents,
    pooled_report_schema,
    report_schema,
)
from compass_bench.domain.claims import Asserted
from compass_bench.domain.design.preregistration import ReportStatus

SCHEMA_DIRECTORY: Final = Path(__file__).parent.parent / "schema"
REGENERATE: Final = "schema/ is stale; run make schema"


def checked_in_example(name: str) -> object:
    return json.loads((SCHEMA_DIRECTORY / "examples" / f"{name}.json").read_text())


def test_the_checked_in_schemas_are_current() -> None:
    checked_in = [json.loads((SCHEMA_DIRECTORY / name).read_text()) for name in (SCHEMA_FILE, POOLED_SCHEMA_FILE)]

    assert checked_in == [report_schema(), pooled_report_schema()], REGENERATE


@pytest.mark.parametrize("name", sorted(example_documents()))
def test_each_checked_in_example_is_current_and_valid(name: str) -> None:
    checked_in = checked_in_example(name)

    assert checked_in == example_json(example_documents()[name]), REGENERATE
    Draft202012Validator(report_schema()).validate(checked_in)


def test_the_examples_hold_a_confirmatory_report_an_asserted_equivalence_and_run_warnings() -> None:
    documents = example_documents().values()

    assert {document.status for document in documents} == set(ReportStatus)
    assert any(
        isinstance(claim, Asserted)
        for document in documents
        for pair in document.result.pairs
        for claim in (pair.equivalences.x, pair.equivalences.y)
    )
    assert any(document.findings for document in documents)


def test_a_pooled_example_carries_a_pool_warning() -> None:
    assert any(document.findings for document in pooled_example_documents().values())


def test_no_two_pooled_examples_share_a_pool_id() -> None:
    pools = [document.pool for document in pooled_example_documents().values()]

    assert len(set(pools)) == len(pools)


@pytest.mark.parametrize("name", sorted(pooled_example_documents()))
def test_each_checked_in_pooled_example_is_current_and_valid(name: str) -> None:
    checked_in = checked_in_example(name)

    assert checked_in == example_json(pooled_example_documents()[name]), REGENERATE
    Draft202012Validator(pooled_report_schema()).validate(checked_in)
