"""compass-bench's one version, which names the report contract, the analysis, and the bundled data together.

A change to any locked component moves VERSION to the next minor version, 2.1 to 2.2; version.lock.json records what
each component held at the current one.
"""

from enum import StrEnum
from typing import Final

# pyproject.toml reads the package version from this line
VERSION: Final = "2.14"


class Version(StrEnum):
    """The version a report document carries; reports are derived on demand, so only the current one exists."""

    CURRENT = VERSION
