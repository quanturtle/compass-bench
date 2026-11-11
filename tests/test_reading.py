import json

import pytest

from compass_bench.contract.corpus import CorpusRow, expected_of
from compass_bench.domain.design.conditions import cross
from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.design.factors import displayed_rating
from compass_bench.domain.elicitation.answer_types import answer_type_strategy
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from compass_bench.domain.instrument.scale import CanonicalRating, Scale
from compass_bench.domain.ledger import FinishReason
from compass_bench.domain.reading.reading import RatingRead, ReadContext
from tests.builders.corpus import BASELINE_CONTEXT, corpus_rows
from tests.builders.design import BOTH_FACTORS
from tests.builders.instrument import asked_scales
from tests.builders.ledger import build_reply


@pytest.mark.parametrize("row", corpus_rows("free_text"), ids=lambda row: row.text)
def test_free_text_corpus(row: CorpusRow) -> None:
    reading = answer_type_strategy(AnswerType.FREE_TEXT).read(build_reply(row.text, row.finish), BASELINE_CONTEXT)

    assert expected_of(reading) == row.expected


@pytest.mark.parametrize("row", corpus_rows("structured"), ids=lambda row: row.text)
def test_structured_corpus(row: CorpusRow) -> None:
    reading = answer_type_strategy(AnswerType.STRUCTURED).read(build_reply(row.text, row.finish), BASELINE_CONTEXT)

    assert expected_of(reading) == row.expected


@pytest.mark.parametrize("answer_type", tuple(AnswerType))
@pytest.mark.parametrize("scale", asked_scales(), ids=lambda scale: f"{len(scale.labels)} points")
def test_a_rating_reads_back_as_its_canonical_rating_under_every_condition(
    answer_type: AnswerType, scale: Scale
) -> None:
    for condition in cross(BOTH_FACTORS, STANDARD_INSTRUCTION):
        for rating in range(1, len(scale.labels) + 1):
            shown = displayed_rating(scale, condition.numeric_mapping, CanonicalRating(rating))
            text = str(shown) if answer_type is AnswerType.FREE_TEXT else json.dumps({"rating": shown})
            reading = answer_type_strategy(answer_type).read(
                build_reply(text, FinishReason.STOP), ReadContext(scale=scale, condition=condition)
            )
            assert isinstance(reading, RatingRead) and reading.canonical == rating
