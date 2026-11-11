"""The version lock: no locked component may change while VERSION stays the locked version."""

from pathlib import Path
from typing import Final

import pytest

from compass_bench.version_lock import VersionLock, current_lock, lock_problem

LOCK_PATH: Final = Path(__file__).parent.parent / "version.lock.json"


def build_lock(version: str, digest: str) -> VersionLock:
    return VersionLock.model_validate({"$comment": "", "version": version, "digests": {"data/catalog.yaml": digest}})


def test_no_locked_component_changes_under_the_locked_version() -> None:
    problem = lock_problem(VersionLock.model_validate_json(LOCK_PATH.read_text()), current_lock())

    assert problem is None, problem


@pytest.mark.parametrize(
    ("version", "digest", "problem"),
    [
        ("2.1", "a", None),
        (
            "2.1",
            "b",
            "changed under version 2.1: data/catalog.yaml; "
            "set VERSION to 2.2 in src/compass_bench/version.py, and run make lock when it is done",
        ),
        ("2.2", "b", None),
        ("2.3", "a", "VERSION 2.3 is neither the locked 2.1 nor the next, 2.2"),
    ],
    ids=["locked, unchanged", "locked, changed", "next version, changed", "skipped version"],
)
def test_only_the_next_version_may_change_a_locked_component(version: str, digest: str, problem: str | None) -> None:
    assert lock_problem(build_lock("2.1", "a"), build_lock(version, digest)) == problem
