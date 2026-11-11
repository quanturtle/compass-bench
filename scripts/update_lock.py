"""Record each locked component's digest under the current VERSION in version.lock.json.

It refuses to replace digests recorded under the same version: a changed component needs the next version first.
"""

from pathlib import Path
from typing import Final

from compass_bench.version_lock import VersionLock, current_lock, lock_problem

LOCK_PATH: Final = Path(__file__).resolve().parent.parent / "version.lock.json"


def recorded_lock(path: Path) -> VersionLock | None:
    """The recorded lock, or None before the first recording."""
    if not path.exists():
        return None
    return VersionLock.model_validate_json(path.read_text(encoding="utf-8"))


def check_lockable(recorded: VersionLock | None, current: VersionLock) -> None:
    """Exit with an error when a component changed under the locked version, or VERSION skips one."""
    problem = None if recorded is None else lock_problem(recorded, current)
    if problem is not None:
        raise SystemExit(problem)
    return


def write_lock(path: Path, lock: VersionLock) -> None:
    path.write_text(lock.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")
    return


def main() -> None:
    current = current_lock()
    check_lockable(recorded_lock(LOCK_PATH), current)
    write_lock(LOCK_PATH, current)
    return


if __name__ == "__main__":
    main()
