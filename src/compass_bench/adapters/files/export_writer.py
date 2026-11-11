"""Exported documents, written to a directory with atomic replacement."""

import json
import os
import tempfile
from pathlib import Path

from pydantic import JsonValue


def write_atomically(path: Path, content: bytes) -> None:
    """Write a unique temporary file, fsync it, and rename it over the target; the old file survives a failure."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        # after the rename the temporary name is gone; after a failure this removes the partial file
        Path(temporary).unlink(missing_ok=True)
    return


def write_document(directory: Path, name: str, document: JsonValue) -> Path:
    """Write the document as indented UTF-8 JSON under `name`, creating the directory; returns the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    write_atomically(path, text.encode())
    return path
