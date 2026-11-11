"""The README's example output and item table repeat the snapshot and the questionnaire file, line for line."""

import json
import re
from pathlib import Path
from typing import Final

REPOSITORY: Final = Path(__file__).parent.parent
README: Final = REPOSITORY / "README.md"
SNAPSHOT: Final = REPOSITORY / "tests" / "snapshots" / "asserted.txt"
QUESTIONNAIRE: Final = (
    REPOSITORY
    / "src"
    / "compass_bench"
    / "data"
    / "questionnaires"
    / "left-vs-right__authoritarian-vs-libertarian.json"
)
EXCERPT_LEAD: Final = "rendered as `tests/snapshots/asserted.txt`"
ITEM_ROW: Final = re.compile(r"^\| (\d+) \| ([xy]) \| `([^`]+)` \| (.+?) \| (.+?) \|$")


def readme_excerpt() -> list[str]:
    """The lines of the fenced block that follows EXCERPT_LEAD."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if EXCERPT_LEAD in line)
    opening = lines.index("```text", start)
    closing = lines.index("```", opening + 1)
    return lines[opening + 1 : closing]


def test_every_line_of_the_readme_excerpt_is_a_line_of_the_asserted_snapshot() -> None:
    snapshot = SNAPSHOT.read_text(encoding="utf-8").splitlines()

    excerpt = readme_excerpt()

    assert excerpt
    for line in excerpt:
        assert line == "" or line in snapshot, line


def test_the_readme_item_table_repeats_the_questionnaire_file_in_order() -> None:
    questions = json.loads(QUESTIONNAIRE.read_text(encoding="utf-8"))["questions"]
    rows = [
        match.groups() for line in README.read_text(encoding="utf-8").splitlines() if (match := ITEM_ROW.match(line))
    ]

    assert len(rows) == len(questions)
    for (number, axis, identifier, negative, positive), (index, question) in zip(
        rows, enumerate(questions), strict=True
    ):
        assert (int(number), axis, identifier) == (index + 1, question["axis"], question["id"])
        assert (negative, positive) == (question["statements"]["negative"], question["statements"]["positive"])
