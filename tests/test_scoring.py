from collections.abc import Callable

import pytest

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity
from compass_bench.domain.design.conditions import Condition, cross
from compass_bench.domain.design.factors import DisplayOrder, NumericMapping, canonical_rating
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.instrument.scale import CanonicalRating, DisplayedRating, Scale, normalize
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.scoring import (
    FacetScore,
    QuestionScore,
    answer_value,
    axis_coverage,
    facet_scores,
    phrasing_values,
    question_scores,
)
from tests.builders.analysis import pending_record, rated_record, scores_on
from tests.builders.design import BOTH_FACTORS
from tests.builders.instrument import (
    FIVE_POINT_LABELS,
    asked_scales,
    build_question,
    build_questionnaire,
    questions_per_axis,
)

SCALE = Scale(labels=FIVE_POINT_LABELS)
QUESTIONNAIRE = build_questionnaire(questions_per_axis(1), FIVE_POINT_LABELS)


def first_listed(condition: Condition) -> DisplayedRating:
    """A content-free responder that picks the number at the top of the list."""
    return DisplayedRating(1 if condition.display_order is DisplayOrder.ASCENDING else 5)


def strongly_agree(condition: Condition) -> DisplayedRating:
    """A content-free responder that always picks the number labelled "Strongly agree"."""
    return DisplayedRating(5 if condition.numeric_mapping is NumericMapping.AGREE_HIGH else 1)


def midpoint(condition: Condition) -> DisplayedRating:
    return DisplayedRating(3)


def responder_records(choose: Callable[[Condition], DisplayedRating]) -> tuple[TrialRecord, ...]:
    """Question x-00, both phrasings, under all four conditions, answered as `choose` displays it."""
    return tuple(
        rated_record(
            "model", "x-00", polarity, canonical_rating(SCALE, condition.numeric_mapping, choose(condition)), condition
        )
        for condition in cross(BOTH_FACTORS, STANDARD_INSTRUCTION)
        for polarity in Polarity
    )


def test_normalize_spans_minus_one_to_one_and_reflecting_the_rating_or_the_polarity_flips_the_value() -> None:
    for scale in asked_scales():
        top = len(scale.labels)
        assert (normalize(scale, CanonicalRating(1)), normalize(scale, CanonicalRating(top))) == (-1.0, 1.0)
        for rating in range(1, top + 1):
            reflected = CanonicalRating(top + 1 - rating)
            assert normalize(scale, reflected) == -normalize(scale, CanonicalRating(rating))
            positive = answer_value(CanonicalRating(rating), Polarity.POSITIVE, scale)
            assert answer_value(CanonicalRating(rating), Polarity.NEGATIVE, scale) == -positive


def test_agreeing_with_both_phrasings_cancels_and_agreeing_with_one_pole_scores_it() -> None:
    records = (
        rated_record("agrees", "x-00", Polarity.POSITIVE, 5),
        rated_record("agrees", "x-00", Polarity.NEGATIVE, 5),
        rated_record("leans", "x-00", Polarity.POSITIVE, 5),
        rated_record("leans", "x-00", Polarity.NEGATIVE, 1),
    )

    scores = question_scores(phrasing_values(records, SCALE), QUESTIONNAIRE, (ModelId("agrees"), ModelId("leans")))

    assert scores == {
        ModelId("agrees"): (QuestionScore(question=QuestionId("x-00"), axis=AxisKey.X, score=0.0),),
        ModelId("leans"): (QuestionScore(question=QuestionId("x-00"), axis=AxisKey.X, score=1.0),),
    }


@pytest.mark.parametrize("choose", [first_listed, strongly_agree, midpoint])
def test_a_responder_that_answers_by_the_layout_alone_scores_zero(
    choose: Callable[[Condition], DisplayedRating],
) -> None:
    records = responder_records(choose)

    scores = question_scores(phrasing_values(records, SCALE), QUESTIONNAIRE, (ModelId("model"),))

    assert scores == {ModelId("model"): (QuestionScore(question=QuestionId("x-00"), axis=AxisKey.X, score=0.0),)}


def test_a_question_with_an_unanswered_phrasing_is_not_scored() -> None:
    records = (rated_record("model", "x-00", Polarity.POSITIVE, 5), pending_record("model", "x-00", Polarity.NEGATIVE))

    assert question_scores(phrasing_values(records, SCALE), QUESTIONNAIRE, (ModelId("model"),)) == {
        ModelId("model"): ()
    }


def test_facet_scores_average_the_scored_questions_of_each_facet_and_list_every_facet() -> None:
    questionnaire = build_questionnaire(
        (
            build_question("x-00", AxisKey.X, "taxation"),
            build_question("x-01", AxisKey.X, "taxation"),
            build_question("x-02", AxisKey.X, "labour"),
            build_question("y-00", AxisKey.Y, "speech"),
        ),
        FIVE_POINT_LABELS,
    )
    scores = scores_on(AxisKey.X, (0.5, 1.0)) + scores_on(AxisKey.Y, (-0.5,))

    assert facet_scores(scores, questionnaire) == (
        FacetScore(axis=AxisKey.X, facet="taxation", questions=2, mean=0.75),
        FacetScore(axis=AxisKey.X, facet="labour", questions=0, mean=None),
        FacetScore(axis=AxisKey.Y, facet="speech", questions=1, mean=-0.5),
    )


def test_coverage_counts_pending_trials_among_the_axis_trials() -> None:
    records = (
        rated_record("model", "x-00", Polarity.POSITIVE, 5),
        pending_record("model", "x-00", Polarity.NEGATIVE),
        rated_record("model", "y-00", Polarity.POSITIVE, 5),
    )

    assert axis_coverage(records, QUESTIONNAIRE) == {ModelId("model"): AxisPair(x=0.5, y=1.0)}
