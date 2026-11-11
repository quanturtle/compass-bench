"""The reply corpus: replies with the reading each must get, on a 5-point scale under the baseline condition."""

from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from compass_bench.contract.corpus import CorpusRow
from compass_bench.domain.design.conditions import BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.reading.reading import ReadContext
from tests.builders.design import build_condition
from tests.builders.instrument import FIVE_POINT_LABELS

CORPUS_DIRECTORY: Final = Path(__file__).parent.parent / "corpus"
BASELINE_CONTEXT: Final = ReadContext(
    scale=Scale(labels=FIVE_POINT_LABELS), condition=build_condition(BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING)
)


def corpus_rows(name: str) -> tuple[CorpusRow, ...]:
    """The rows of `tests/corpus/<name>.json`."""
    text = (CORPUS_DIRECTORY / f"{name}.json").read_text()
    return TypeAdapter(tuple[CorpusRow, ...]).validate_json(text)
