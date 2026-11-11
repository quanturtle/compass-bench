"""Agreement between the tool's readings and a second reader's, over a sample from scripts/sample_replies.py."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from compass_bench.app.reader_sample import AgreementTable, BlindRow, SampleRow, agreement


def parse_arguments(argv: Sequence[str]) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(description="Cohen's kappa between the tool and a second reader.")
    parser.add_argument("--sample", type=Path, required=True, help="the sample with the tool's readings")
    parser.add_argument("--labelled", type=Path, required=True, help="the blinded copy, filled in by hand")
    arguments = parser.parse_args(argv)
    sample: Path = arguments.sample
    labelled: Path = arguments.labelled
    return sample, labelled


def kappa_text(kappa: float | None) -> str:
    return "undefined" if kappa is None else f"{kappa:.2f}"


def render(table: AgreementTable) -> str:
    """A markdown table for docs/questionnaire.md."""
    lines = (
        "| Category | Rows | κ |",
        "|---|---|---|",
        f"| reading kind | {table.rows - table.unread} | {kappa_text(table.kind)} |",
        f"| rating against the rest | {table.rows - table.unread} | {kappa_text(table.rating)} |",
        f"| decline against the rest | {table.rows - table.unread} | {kappa_text(table.decline)} |",
        f"| format failure against the rest | {table.rows - table.unread} | {kappa_text(table.failure)} |",
        f"| hedged, among rows both read as ratings | {table.both_ratings} | {kappa_text(table.hedged)} |",
        f"| displayed number, among rows both read as ratings | {table.both_ratings} | {kappa_text(table.displayed)} |",
        f"| left unread by the second reader | {table.unread} | |",
    )
    return "\n".join(lines)


def main() -> None:
    sample_path, labelled_path = parse_arguments(sys.argv[1:])
    rows = TypeAdapter(tuple[SampleRow, ...]).validate_json(sample_path.read_text(encoding="utf-8"))
    labelled = TypeAdapter(tuple[BlindRow, ...]).validate_json(labelled_path.read_text(encoding="utf-8"))
    table = agreement(rows, {row.sample_id: row.second for row in labelled})
    print(render(table))
    return


if __name__ == "__main__":
    main()
