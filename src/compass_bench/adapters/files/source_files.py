"""SourceReader over the local filesystem."""

import json
from collections.abc import Callable
from pathlib import Path, PurePath

import yaml

from compass_bench.adapters.files.strict_yaml import parse_yaml
from compass_bench.ports.sources import InvalidSource


def read_text(file: Path, path: PurePath) -> str:
    """The file's UTF-8 text; `path` is the name an error reports."""
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidSource(f"{path}: {error}") from error


def yaml_error_text(path: PurePath, error: yaml.YAMLError) -> str:
    """One line: the file, the line and column the parser stopped at, and the problem it found."""
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        mark = error.problem_mark
        return f"{path}:{mark.line + 1}:{mark.column + 1}: {error.problem}"
    return f"{path}: {' '.join(str(error).split())}"


def reject_repeated_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """object_pairs_hook for json.loads: raise ValueError on a repeated key instead of keeping the last."""
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise ValueError(f"repeated key {key!r}")
        mapping[key] = value
    return mapping


def never_committed(file: Path) -> bool:
    """The answer of a reader given no version control to ask: no file counts as committed."""
    return False


class SourceFiles:
    def __init__(self, root: Path, committed: Callable[[Path], bool] = never_committed) -> None:
        """Relative paths resolve against `root`; an absolute path stays as it is.
        `committed` says whether version control holds a file as it stands."""
        self.root = root
        self.committed = committed
        return

    def read_yaml(self, path: PurePath) -> str:
        """As JSON text; raises InvalidSource for an unreadable file, a repeated key, or a non-mapping root."""
        try:
            document = parse_yaml(read_text(self.root / path, path))
        except yaml.YAMLError as error:
            raise InvalidSource(yaml_error_text(path, error)) from error
        if not isinstance(document, dict):
            raise InvalidSource(f"{path}: the document is not a mapping")
        try:
            return json.dumps(document, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise InvalidSource(f"{path}: {error}") from error

    def exists(self, path: PurePath) -> bool:
        return (self.root / path).is_file()

    def is_committed(self, path: PurePath) -> bool:
        return self.committed((self.root / path).resolve())

    def read_json(self, path: PurePath) -> str:
        """The text as it is, once it parses as JSON with no repeated key."""
        text = read_text(self.root / path, path)
        try:
            json.loads(text, object_pairs_hook=reject_repeated_keys)
        except ValueError as error:
            raise InvalidSource(f"{path}: {error}") from error
        return text
