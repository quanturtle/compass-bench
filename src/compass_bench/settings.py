"""Environment settings, read once when a command starts and passed down."""

import subprocess
from collections.abc import Iterable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, SecretStr

PACKAGE_NAME: Final = "compass-bench"
PACKAGE_DIRECTORY: Final = Path(__file__).parent
DATABASE_URL_VARIABLE: Final = "COMPASS_BENCH_DATABASE_URL"
CODE_REVISION_VARIABLE: Final = "COMPASS_BENCH_CODE_REVISION"
DIRTY_SUFFIX: Final = "-dirty"


class MissingSetting(Exception):
    """A required environment variable is unset or blank."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    database_url: SecretStr
    code_revision: str


def git_output(directory: Path, *arguments: str) -> str | None:
    """Stdout of a git command run in `directory`, or None when git is not installed or the command fails."""
    try:
        completed = subprocess.run(["git", *arguments], cwd=directory, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def checkout_revision(directory: Path) -> str | None:
    """The checkout's short commit, with `-dirty` when a file under `directory` differs from it or is untracked.

    None when git tracks no file under `directory`, as for a copy installed into a virtual environment."""
    if not git_output(directory, "ls-files", "--", "."):
        return None
    head = git_output(directory, "rev-parse", "--short", "HEAD")
    changes = git_output(directory, "status", "--porcelain", "--", ".")
    if head is None or changes is None:
        return None
    return head + DIRTY_SUFFIX if changes else head


def code_revision(environ: Mapping[str, str], package_directory: Path = PACKAGE_DIRECTORY) -> str:
    """The revision stamp from the environment, else the package's git checkout, else the installed package version."""
    return (
        environ.get(CODE_REVISION_VARIABLE, "").strip() or checkout_revision(package_directory) or version(PACKAGE_NAME)
    )


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Raises MissingSetting when the database URL is unset; it has no default."""
    database_url = environ.get(DATABASE_URL_VARIABLE, "").strip()
    if not database_url:
        raise MissingSetting(f"{DATABASE_URL_VARIABLE} is not set")
    return Settings(database_url=SecretStr(database_url), code_revision=code_revision(environ))


def load_api_keys(environ: Mapping[str, str], variables: Iterable[str]) -> dict[str, SecretStr]:
    """Read the key variables the catalog names; raises MissingSetting for any that is unset."""
    keys = {variable: environ.get(variable, "").strip() for variable in sorted(set(variables))}
    missing = [variable for variable, key in keys.items() if not key]
    if missing:
        raise MissingSetting(f"API key variables not set: {', '.join(missing)}")
    return {variable: SecretStr(key) for variable, key in keys.items()}
