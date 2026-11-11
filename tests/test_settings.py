import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Final

import pytest

from compass_bench.settings import CODE_REVISION_VARIABLE, PACKAGE_NAME, code_revision

GIT_IDENTITY: Final = ("-c", "user.name=Jane Doe", "-c", "user.email=user@example.com", "-c", "commit.gpgsign=false")


def git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *GIT_IDENTITY, *arguments], cwd=directory, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def committed_package(root: Path) -> Path:
    """A git checkout at `root` holding one committed package directory, which is returned."""
    package = root / "package"
    package.mkdir()
    (package / "__init__.py").write_text("")
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "--no-verify", "-m", "Add the package")
    return package


def test_the_variable_overrides_the_checkout(tmp_path: Path) -> None:
    package = committed_package(tmp_path)

    assert code_revision({CODE_REVISION_VARIABLE: "release-1"}, package) == "release-1"


def test_a_clean_checkout_gives_its_short_commit(tmp_path: Path) -> None:
    package = committed_package(tmp_path)

    assert code_revision({}, package) == git(tmp_path, "rev-parse", "--short", "HEAD")


@pytest.mark.parametrize("name", ["__init__.py", "new_module.py"], ids=["modified", "untracked"])
def test_a_change_in_the_package_marks_the_commit_dirty(tmp_path: Path, name: str) -> None:
    package = committed_package(tmp_path)
    (package / name).write_text("x = 1\n")

    assert code_revision({}, package) == git(tmp_path, "rev-parse", "--short", "HEAD") + "-dirty"


def test_a_change_outside_the_package_leaves_the_commit_clean(tmp_path: Path) -> None:
    package = committed_package(tmp_path)
    (tmp_path / "README.md").write_text("notes\n")

    assert code_revision({}, package) == git(tmp_path, "rev-parse", "--short", "HEAD")


def test_an_ignored_copy_in_a_checkout_gives_the_package_version(tmp_path: Path) -> None:
    committed_package(tmp_path)
    (tmp_path / ".gitignore").write_text(".venv/\n")
    installed = tmp_path / ".venv" / "package"
    installed.mkdir(parents=True)
    (installed / "__init__.py").write_text("")

    assert code_revision({}, installed) == version(PACKAGE_NAME)


def test_outside_a_checkout_the_package_version_is_used(tmp_path: Path) -> None:
    assert code_revision({}, tmp_path) == version(PACKAGE_NAME)
