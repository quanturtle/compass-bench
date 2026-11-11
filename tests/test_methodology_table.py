"""METHODOLOGY's calibration table is printed from audits/statistical-audit.json; the two must agree, row for row."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final

REPOSITORY: Final = Path(__file__).parent.parent
METHODOLOGY: Final = REPOSITORY / "METHODOLOGY.md"
AUDIT: Final = REPOSITORY / "audits" / "statistical-audit.json"
SCRIPT: Final = REPOSITORY / "scripts" / "statistical_audit.py"
TABLE_HEADER: Final = "| Scenario | Questions per axis | Stance |"


def load_audit() -> ModuleType:
    location = importlib.util.spec_from_file_location("statistical_audit", SCRIPT)
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    location.loader.exec_module(module)
    return module


def table_rows() -> list[str]:
    """The rows of the calibration table: every table line after its header and rule, in order."""
    lines = METHODOLOGY.read_text(encoding="utf-8").splitlines()
    header = next(index for index, line in enumerate(lines) if line.startswith(TABLE_HEADER))
    rows: list[str] = []
    for line in lines[header + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def test_the_calibration_table_repeats_the_audit_results_row_for_row() -> None:
    audit = load_audit()

    printed = [audit.table_row(result) for result in audit.load_results(AUDIT)]

    assert table_rows() == printed
