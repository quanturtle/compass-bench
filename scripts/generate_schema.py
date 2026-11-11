"""Write the report and pooled report schemas, named after the version, and schema/examples/ from the contract models.

CI fails if the output differs."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pydantic import JsonValue

from compass_bench.contract.schema import (
    POOLED_SCHEMA_FILE,
    SCHEMA_FILE,
    example_documents,
    example_json,
    pooled_example_documents,
    pooled_report_schema,
    report_schema,
)

REPOSITORY: Final = Path(__file__).resolve().parent.parent
EXAMPLES_DIRECTORY: Final = "examples"


def parse_arguments(argv: Sequence[str]) -> Path:
    """The output directory; defaults to schema/ at the repository root."""
    parser = argparse.ArgumentParser(description="Write the report JSON Schema and its example documents.")
    parser.add_argument("--out", type=Path, default=REPOSITORY / "schema", help="the directory to write to")
    out: Path = parser.parse_args(argv).out
    return out


def write_json(path: Path, document: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return


def write_examples(directory: Path) -> None:
    """One file per example document, single-run and pooled; examples no longer generated are removed."""
    examples = directory / EXAMPLES_DIRECTORY
    documents = {
        **{name: example_json(document) for name, document in example_documents().items()},
        **{name: example_json(document) for name, document in pooled_example_documents().items()},
    }
    for stale in examples.glob("*.json"):
        if stale.stem not in documents:
            stale.unlink()
    for name, document in documents.items():
        write_json(examples / f"{name}.json", document)
    return


def main() -> None:
    out = parse_arguments(sys.argv[1:])
    write_json(out / SCHEMA_FILE, report_schema())
    write_json(out / POOLED_SCHEMA_FILE, pooled_report_schema())
    write_examples(out)
    return


if __name__ == "__main__":
    main()
