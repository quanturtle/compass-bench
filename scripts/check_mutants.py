"""Fail when the mutation tests leave a mutant that tests/equivalent_mutants.json does not explain.

Reads the lines `mutmut results --all true` prints, `<mutant>: <status>`. A mutant that is not killed must be listed
as equivalent, with the reason no test can tell it from the original, and a listed mutant must still exist and still
survive, so the list cannot go stale. mutmut numbers a function's mutants in source order: an edit to a function
renumbers them, and its listed mutants then need judging again.
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

EQUIVALENT_PATH: Final = Path(__file__).resolve().parent.parent / "tests" / "equivalent_mutants.json"
RESULT_LINE: Final = re.compile(r"\s*(?P<mutant>\S+): (?P<status>.+)")
KILLED: Final = "killed"
SURVIVED: Final = "survived"


def parse_arguments(argv: Sequence[str]) -> Path:
    parser = argparse.ArgumentParser(description="Check the mutation test results against the equivalent mutants.")
    parser.add_argument("results", type=Path, help="the output of `mutmut results --all true`")
    results: Path = parser.parse_args(argv).results
    return results


def mutant_statuses(text: str) -> dict[str, str]:
    """Each mutant's status, from the lines that read `<mutant>: <status>`."""
    matches = (RESULT_LINE.fullmatch(line) for line in text.splitlines())
    return {match["mutant"]: match["status"].strip() for match in matches if match is not None}


def listed_equivalent(path: Path) -> dict[str, str]:
    """Each mutant judged equivalent, with its reason."""
    listed: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return listed


def unexplained(statuses: Mapping[str, str], equivalent: Mapping[str, str]) -> list[str]:
    """One line per mutant that is not killed, unless it survived and is listed as equivalent."""
    return [
        f"{mutant}: {status}, and not listed as equivalent"
        for mutant, status in sorted(statuses.items())
        if status != KILLED and not (status == SURVIVED and mutant in equivalent)
    ]


def stale(statuses: Mapping[str, str], equivalent: Mapping[str, str]) -> list[str]:
    """One line per listed mutant that no longer exists, no longer survives, or has no reason."""
    missing = [f"{mutant}: listed as equivalent, but no such mutant" for mutant in equivalent if mutant not in statuses]
    killed = [f"{mutant}: listed as equivalent, but killed" for mutant in equivalent if statuses.get(mutant) == KILLED]
    bare = [f"{mutant}: listed as equivalent without a reason" for mutant, reason in equivalent.items() if not reason]
    return sorted(missing + killed + bare)


def mutant_problems(statuses: Mapping[str, str], equivalent: Mapping[str, str]) -> list[str]:
    """Why the results fail the check, one line each; empty when they pass."""
    if not statuses:
        return ["the results name no mutant"]
    return unexplained(statuses, equivalent) + stale(statuses, equivalent)


def summary(statuses: Mapping[str, str], equivalent: Mapping[str, str]) -> str:
    killed = sum(status == KILLED for status in statuses.values())
    return f"{len(statuses)} mutants: {killed} killed, {len(equivalent)} listed as equivalent"


def report(problems: Sequence[str], passed: str) -> None:
    """Print `passed`, or the problems on stderr with exit code 1."""
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    print(passed)
    return


def main() -> None:
    results = parse_arguments(sys.argv[1:])
    statuses = mutant_statuses(results.read_text(encoding="utf-8"))
    equivalent = listed_equivalent(EQUIVALENT_PATH)
    report(mutant_problems(statuses, equivalent), summary(statuses, equivalent))
    return


if __name__ == "__main__":
    main()
