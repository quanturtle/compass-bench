"""Unanswered trials: the questions they drop, the bound they leave, and the fill that flips a side of 0."""

from collections.abc import Sequence

import pytest

from compass_bench.domain.axis_pair import AxisKey, Polarity, PolarityPair
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.missing import (
    AxisUnanswered,
    Bound,
    DroppedQuestion,
    axis_unanswered,
    clears_positive,
    filled_scores,
    fills,
    gap_bound,
    model_unanswered,
    own_unanswered,
)
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.scoring import phrasing_values, question_scores
from tests.builders.analysis import declined_record, pending_record, rated_record
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis

QUESTIONNAIRE = build_questionnaire(questions_per_axis(4), FIVE_POINT_LABELS)
SCALE = QUESTIONNAIRE.scale
LEVEL = 0.975
MODEL = ModelId("model")
OTHER = ModelId("other")


def answered(model: str, rating: int, questions: Sequence[str]) -> tuple[TrialRecord, ...]:
    """Both statements of each question answered at `rating`."""
    return tuple(
        rated_record(model, question, polarity, rating, repetition=0) for question in questions for polarity in Polarity
    )


def unanswered_on(model: str, records: Sequence[TrialRecord], axis: AxisKey = AxisKey.X) -> AxisUnanswered:
    values = phrasing_values(records, SCALE)
    scores = question_scores(values, QUESTIONNAIRE, (ModelId(model),))[ModelId(model)]
    return axis_unanswered(ModelId(model), axis, values, records, scores, QUESTIONNAIRE, LEVEL)


def test_a_question_with_an_unanswered_statement_is_dropped_and_declines_count_toward_their_pole() -> None:
    records = (
        *answered("model", 5, ("x-00", "x-01", "x-02")),
        rated_record("model", "x-03", Polarity.POSITIVE, 5),
        declined_record("model", "x-03", Polarity.NEGATIVE),
        pending_record("model", "y-00", Polarity.POSITIVE),
    )

    result = unanswered_on("model", records)

    assert result.trials == 1
    assert result.declined == PolarityPair(negative=1, positive=0)
    assert result.dropped == (DroppedQuestion(question=QuestionId("x-03"), unanswered=1),)


def test_the_bound_fills_each_unanswered_trial_at_either_end_and_scores_the_dropped_question() -> None:
    # three questions cancel to 0; the fourth has one answer at +1 toward the positive pole and one unanswered
    records = (
        *answered("model", 4, ("x-00", "x-01", "x-02")),
        rated_record("model", "x-03", Polarity.POSITIVE, 5),
        declined_record("model", "x-03", Polarity.NEGATIVE),
    )

    result = unanswered_on("model", records)

    # x-03 scores (1 + fill) / 2: 0 at the low fill and 1 at the high one, averaged over four questions
    assert result.bound == Bound(low=0.0, high=0.25, filled=1)


def test_the_bound_width_is_twice_the_unanswered_share_when_every_trial_weighs_the_same() -> None:
    # 8 trials, one per statement, 1 of them unanswered
    records = (
        *answered("model", 3, ("x-00", "x-01", "x-03")),
        rated_record("model", "x-02", Polarity.POSITIVE, 3),
        pending_record("model", "x-02", Polarity.NEGATIVE),
    )

    result = unanswered_on("model", records)

    assert result.bound is not None
    assert result.bound.high - result.bound.low == pytest.approx(2 * 1 / 8)


def test_without_unanswered_trials_the_bound_is_the_position_and_nothing_flips() -> None:
    result = unanswered_on("model", answered("model", 5, ("x-00", "x-01", "x-02", "x-03")))

    assert result.bound == Bound(low=0.0, high=0.0, filled=0)
    assert result.flip is None
    assert result.dropped == ()


def test_the_bound_is_undefined_without_a_question_to_score() -> None:
    assert unanswered_on("model", ()).bound is None


def test_the_flip_is_the_highest_fill_at_which_a_positive_interval_no_longer_clears_zero() -> None:
    # agreement toward the positive pole on every answered trial, one trial unanswered
    records = (
        *(rated_record("model", question, Polarity.POSITIVE, 5) for question in ("x-00", "x-01", "x-02", "x-03")),
        *(rated_record("model", question, Polarity.NEGATIVE, 1) for question in ("x-00", "x-01", "x-02")),
        pending_record("model", "x-03", Polarity.NEGATIVE),
    )

    result = unanswered_on("model", records)

    assert result.flip is not None and result.flip in fills()
    # filling at the flip breaks the claim and filling one step above keeps it
    values = phrasing_values(records, SCALE)
    unanswered = own_unanswered(MODEL, AxisKey.X, records, QUESTIONNAIRE)
    step = fills()[1] - fills()[0]
    at_flip = filled_scores(MODEL, AxisKey.X, values, unanswered, QUESTIONNAIRE, result.flip)
    above_flip = filled_scores(MODEL, AxisKey.X, values, unanswered, QUESTIONNAIRE, result.flip + step)
    assert not clears_positive(at_flip, LEVEL)
    assert clears_positive(above_flip, LEVEL)


def test_the_flip_is_undefined_when_the_interval_contains_zero_as_it_stands() -> None:
    records = (*answered("model", 3, ("x-00", "x-01", "x-02")), pending_record("model", "x-03", Polarity.POSITIVE))

    assert unanswered_on("model", records).flip is None


def test_model_unanswered_covers_both_axes() -> None:
    records = (*answered("model", 4, ("x-00", "x-01")), pending_record("model", "y-00", Polarity.POSITIVE))

    result = model_unanswered(MODEL, phrasing_values(records, SCALE), records, (), QUESTIONNAIRE, LEVEL)

    assert (result.x.trials, result.y.trials) == (0, 1)


def test_the_gap_bound_fills_the_two_models_in_opposite_directions() -> None:
    records = (
        *answered("model", 4, ("x-00", "x-01")),
        *answered("other", 4, ("x-00",)),
        rated_record("other", "x-01", Polarity.POSITIVE, 4),
        pending_record("other", "x-01", Polarity.NEGATIVE),
    )

    bound = gap_bound(MODEL, OTHER, AxisKey.X, phrasing_values(records, SCALE), records, QUESTIONNAIRE)

    # other's x-01 scores (0.5 + fill) / 2 against model's 0, averaged over two shared questions
    assert bound == Bound(low=-0.125, high=0.375, filled=1)


def test_the_gap_bound_is_undefined_without_a_shared_question() -> None:
    records = (*answered("model", 4, ("x-00",)), *answered("other", 4, ("x-01",)))

    assert gap_bound(MODEL, OTHER, AxisKey.X, phrasing_values(records, SCALE), records, QUESTIONNAIRE) is None
