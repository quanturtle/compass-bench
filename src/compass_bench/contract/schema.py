"""JSON Schemas and example documents for the frontend. scripts/generate_schema.py writes them to schema/."""

from typing import Final

from pydantic import BaseModel, JsonValue

from compass_bench.app.pool import pooled_documents
from compass_bench.contract.examples import example_endpoints, example_runs, pooled_example_runs
from compass_bench.contract.v2 import PooledReportDocument, ReportDocument, report_document
from compass_bench.domain.analysis import analyze
from compass_bench.domain.ids import content_hash
from compass_bench.domain.pooling import pooled_analyses
from compass_bench.version import VERSION

SCHEMA_FILE: Final = f"report-{VERSION}.json"
POOLED_SCHEMA_FILE: Final = f"pooled-report-{VERSION}.json"
SCHEMA_COMMENT: Final = "Generated from compass_bench.contract.v2 by scripts/generate_schema.py. Do not edit."
SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
EXAMPLE_SIGNIFICANT_DIGITS: Final = 10


def document_schema(document: type[BaseModel]) -> dict[str, JsonValue]:
    """JSON Schema of a document model, carrying SCHEMA_COMMENT as its $comment."""
    schema: dict[str, JsonValue] = document.model_json_schema(mode="serialization")
    return {"$schema": SCHEMA_DIALECT, "$comment": SCHEMA_COMMENT, **schema}


def report_schema() -> dict[str, JsonValue]:
    return document_schema(ReportDocument)


def pooled_report_schema() -> dict[str, JsonValue]:
    return document_schema(PooledReportDocument)


def example_documents() -> dict[str, ReportDocument]:
    """Synthetic documents covering an asserted claim, a withheld claim, and a partial run."""
    return {
        name: report_document(
            planned, example_endpoints(), analyze(planned.trials, entries, planned.questionnaire, planned.spec)
        )
        for name, (planned, entries) in example_runs().items()
    }


def pooled_example_documents() -> dict[str, PooledReportDocument]:
    """Synthetic pooled documents: an example whose runs form one pool keeps its name, and one whose runs form
    several pools, one per scale, names each `<example>-<scale>`."""
    documents: dict[str, PooledReportDocument] = {}
    for name, runs in pooled_example_runs().items():
        endpoints = {planned.run.run_id: example_endpoints() for planned, _ in runs}
        pooled = pooled_documents(pooled_analyses(runs), endpoints)
        if len(pooled) == 1:
            documents[name] = pooled[0]
            continue
        for document in pooled:
            documents[f"{name}-{document.scale}"] = document
    return documents


def rounded(value: JsonValue) -> JsonValue:
    """`value` with every float at EXAMPLE_SIGNIFICANT_DIGITS significant digits."""
    if isinstance(value, float):
        return float(f"{value:.{EXAMPLE_SIGNIFICANT_DIGITS}g}")
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def example_json(document: BaseModel) -> JsonValue:
    """An example document as the JSON that is checked in and hashed, floats rounded.
    Platforms disagree on a float's last digits; the checked-in examples and their digests must not."""
    return rounded(document.model_dump(mode="json"))


def example_digests() -> dict[str, str]:
    """content_hash of each example document, single-run and pooled: the version lock records them."""
    documents: dict[str, BaseModel] = {**example_documents(), **pooled_example_documents()}
    return {name: content_hash(example_json(document)) for name, document in documents.items()}
