"""The mutation test check: which results pass against the list of mutants judged equivalent."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final

SCRIPT: Final = Path(__file__).parent.parent / "scripts" / "check_mutants.py"


def load_check() -> ModuleType:
    """The check script as a module; it lives outside the package."""
    location = importlib.util.spec_from_file_location("check_mutants", SCRIPT)
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    location.loader.exec_module(module)
    return module


CHECK: Final = load_check()
EQUIVALENT: Final = {"stats.x_mean__mutmut_2": "divides by a polarity of +1 or -1"}


def test_the_results_are_read_one_mutant_a_line_and_other_lines_are_skipped() -> None:
    text = "Running\n    stats.x_mean__mutmut_1: killed\n    stats.x_mean__mutmut_2: caught by type check\n"

    assert CHECK.mutant_statuses(text) == {
        "stats.x_mean__mutmut_1": "killed",
        "stats.x_mean__mutmut_2": "caught by type check",
    }


def test_killed_mutants_and_a_listed_survivor_pass() -> None:
    statuses = {"stats.x_mean__mutmut_1": "killed", "stats.x_mean__mutmut_2": "survived"}

    assert CHECK.mutant_problems(statuses, EQUIVALENT) == []


def test_a_survivor_that_is_not_listed_fails() -> None:
    statuses = {"stats.x_mean__mutmut_2": "survived", "stats.x_mean__mutmut_3": "survived"}

    assert CHECK.mutant_problems(statuses, EQUIVALENT) == [
        "stats.x_mean__mutmut_3: survived, and not listed as equivalent"
    ]


def test_a_listed_mutant_that_is_neither_killed_nor_survived_fails() -> None:
    statuses = {"stats.x_mean__mutmut_2": "timeout"}

    assert CHECK.mutant_problems(statuses, EQUIVALENT) == [
        "stats.x_mean__mutmut_2: timeout, and not listed as equivalent"
    ]


def test_a_listed_mutant_that_is_gone_or_killed_fails() -> None:
    gone = CHECK.mutant_problems({"stats.x_mean__mutmut_1": "killed"}, EQUIVALENT)
    killed = CHECK.mutant_problems({"stats.x_mean__mutmut_2": "killed"}, EQUIVALENT)

    assert gone == ["stats.x_mean__mutmut_2: listed as equivalent, but no such mutant"]
    assert killed == ["stats.x_mean__mutmut_2: listed as equivalent, but killed"]


def test_results_without_a_mutant_fail() -> None:
    assert CHECK.mutant_problems({}, {}) == ["the results name no mutant"]


def test_every_listed_mutant_carries_a_reason() -> None:
    listed = CHECK.listed_equivalent(CHECK.EQUIVALENT_PATH)

    assert listed and all(reason.strip() for reason in listed.values())
