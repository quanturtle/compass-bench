"""Input documents: experiment and catalog YAML, questionnaire JSON."""

from pathlib import PurePath
from typing import Protocol


class InvalidSource(Exception):
    """A source file is unreadable, malformed, or repeats a key."""


class SourceReader(Protocol):
    def read_yaml(self, path: PurePath) -> str:
        """The document as JSON text, so strict models validate it in JSON mode."""
        ...

    def read_json(self, path: PurePath) -> str: ...

    def exists(self, path: PurePath) -> bool:
        """Whether a source file is there to read; the preregistration check needs only that."""
        ...
