"""The response profile: use of the scale, the split of question scores, and statement agreement."""

import math

import pytest

from compass_bench.domain.axis_pair import AxisKey, Polarity
from compass_bench.domain.design.factors import DisplayOrder, NumericMapping
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.instrument.scale import CanonicalRating, Scale
from compass_bench.domain.profile import (
    RatingProfile,
    ScaleUse,
    ScoreSplit,
    StatementAgreement,
    axis_profile,
    model_profile,
    rating_profile,
    scale_use,
    score_split,
    statement_agreement,
)
from compass_bench.domain.scoring import FacetScore, facet_scores, phrasing_values, question_scores
from tests.builders.analysis import rated_record, scores_on
from tests.builders.design import build_condition
from tests.builders.instrument import FIVE_POINT_LABELS, FOUR_POINT_LABELS, build_questionnaire, questions_per_axis

QUESTIONNAIRE = build_questionnaire(questions_per_axis(4), FIVE_POINT_LABELS)
FIVE = Scale(labels=FIVE_POINT_LABELS)
FOUR = Scale(labels=FOUR_POINT_LABELS)
MODEL = ModelId("model")
X_00 = QuestionId("x-00")
DESCENDING = build_condition(DisplayOrder.DESCENDING, NumericMapping.AGREE_HIGH)


def ratings(*values: int) -> list[CanonicalRating]:
    return [CanonicalRating(value) for value in values]


def test_the_rating_profile_shares_the_answers_over_the_scale_points() -> None:
    profile = rating_profile(ratings(1, 3, 3, 5), FIVE)

    assert (profile.answered, profile.shares) == (4, (0.25, 0.0, 0.5, 0.0, 0.25))
    assert (profile.midpoint_share, profile.ends_share) == (0.5, 0.5)
    assert profile.rating_sd == pytest.approx(1.633, abs=1e-3)


def test_a_scale_without_a_midpoint_has_no_midpoint_share_and_no_answers_give_empty_shares() -> None:
    assert rating_profile(ratings(2, 3), FOUR).midpoint_share is None
    assert rating_profile([], FIVE) == RatingProfile(
        answered=0, shares=(0.0,) * 5, midpoint_share=0.0, ends_share=0.0, rating_sd=None
    )


def test_the_score_split_counts_each_side_of_zero_and_the_facets_opposing_the_position() -> None:
    scores = scores_on(AxisKey.X, (0.5, -0.5, 0.0, 0.8))
    facets = (
        FacetScore(axis=AxisKey.X, facet="a", questions=2, mean=-0.2),
        FacetScore(axis=AxisKey.X, facet="b", questions=2, mean=0.6),
        FacetScore(axis=AxisKey.Y, facet="c", questions=1, mean=-0.9),
    )

    split = score_split(scores, facets, AxisKey.X)

    assert (split.positive, split.negative, split.zero, split.opposing_facets) == (2, 1, 1, 1)
    assert split.mean_absolute == pytest.approx(0.45)
    assert split.facet_balanced == pytest.approx(0.2)
    assert score_split((), (), AxisKey.X).mean_absolute is None


def test_the_farthest_scores_are_named_farthest_first_with_a_tie_kept_in_questionnaire_order() -> None:
    # position 0.1: distances 0.8, 0.5, 0.0, 0.5, 0.8
    scores = scores_on(AxisKey.X, (0.9, -0.4, 0.1, 0.6, -0.7))

    farthest = score_split(scores, (), AxisKey.X).farthest

    assert [score.question for score in farthest] == ["x-00", "x-04", "x-01"]
    assert score_split(scores_on(AxisKey.X, (0.4,)), (), AxisKey.X).farthest == ()


def test_scale_use_differs_when_one_rating_spread_is_one_and_a_half_times_the_other() -> None:
    narrow = rating_profile(ratings(2, 3, 3, 4), FIVE)
    broad = rating_profile(ratings(1, 1, 5, 5), FIVE)
    middling = rating_profile(ratings(2, 2, 4, 4), FIVE)

    assert scale_use(narrow, broad) == ScaleUse(sd_first=narrow.rating_sd, sd_second=broad.rating_sd, differs=True)
    assert scale_use(narrow, middling).differs is False
    assert scale_use(narrow, rating_profile(ratings(3), FIVE)).differs is False
    assert scale_use(narrow, rating_profile(ratings(3, 3, 3), FIVE)).differs is False


def test_scale_use_differs_at_exactly_one_and_a_half_times_the_spread() -> None:
    narrow = RatingProfile(answered=4, shares=(0.0,) * 5, midpoint_share=0.0, ends_share=0.0, rating_sd=1.0)
    broad = narrow.model_copy(update={"rating_sd": 1.5})

    assert scale_use(narrow, broad).differs is True


def test_two_answers_have_a_rating_spread() -> None:
    # ratings 2 and 4 lie 1 from their mean: the sample standard deviation is the square root of 2
    assert rating_profile(ratings(2, 4), FIVE).rating_sd == pytest.approx(math.sqrt(2))


def test_two_scores_are_both_farthest_from_their_position() -> None:
    # two scores lie equally far from their mean, so both are named, in questionnaire order
    farthest = score_split(scores_on(AxisKey.X, (0.25, 0.75)), (), AxisKey.X).farthest

    assert [score.question for score in farthest] == ["x-00", "x-01"]


def test_the_facet_balanced_position_is_undefined_while_a_facet_of_the_axis_is_unscored() -> None:
    scores = scores_on(AxisKey.X, (0.5, 0.3))
    facets = (
        FacetScore(axis=AxisKey.X, facet="a", questions=2, mean=0.4),
        FacetScore(axis=AxisKey.X, facet="b", questions=0, mean=None),
    )

    assert score_split(scores, facets, AxisKey.X).facet_balanced is None
    assert score_split((), (), AxisKey.X).facet_balanced is None


def test_statement_agreement_counts_one_sided_statements_and_the_variance_between_them() -> None:
    agreement = statement_agreement(
        {
            (MODEL, X_00, Polarity.POSITIVE): ratings(4, 5, 5, 4),
            (MODEL, X_00, Polarity.NEGATIVE): ratings(2, 2, 1, 3),
            (MODEL, QuestionId("x-01"), Polarity.POSITIVE): ratings(3),
        },
        FIVE,
    )

    assert (agreement.one_sided, agreement.statements) == (1, 2)
    assert agreement.icc is not None and 0.5 < agreement.icc < 1.0


def test_statements_rated_the_same_in_every_cell_and_statements_spread_wide_are_counted_among_the_repeated() -> None:
    agreement = statement_agreement(
        {
            (MODEL, X_00, Polarity.POSITIVE): ratings(3, 3, 3, 3),
            (MODEL, X_00, Polarity.NEGATIVE): ratings(2, 4, 2, 4),
            (MODEL, QuestionId("x-01"), Polarity.POSITIVE): ratings(3, 4),
            (MODEL, QuestionId("x-01"), Polarity.NEGATIVE): ratings(5),
        },
        FIVE,
    )

    assert (agreement.identical, agreement.wide, agreement.statements) == (1, 1, 3)


def test_identical_answers_within_every_statement_give_an_icc_of_one_and_one_statement_none() -> None:
    perfect = statement_agreement(
        {(MODEL, X_00, Polarity.POSITIVE): ratings(5, 5), (MODEL, X_00, Polarity.NEGATIVE): ratings(1, 1)}, FIVE
    )
    alone = statement_agreement({(MODEL, X_00, Polarity.POSITIVE): ratings(5, 4)}, FIVE)

    assert perfect.icc == pytest.approx(1.0)
    assert alone == StatementAgreement(one_sided=1, identical=0, wide=0, wide_range=2, statements=1, icc=None)


def test_the_axis_profile_reads_the_models_own_answers_on_the_axis() -> None:
    records = (
        rated_record("model", "x-00", Polarity.POSITIVE, 5),
        rated_record("model", "x-00", Polarity.POSITIVE, 4, DESCENDING),
        rated_record("model", "x-00", Polarity.NEGATIVE, 1),
        rated_record("model", "x-00", Polarity.NEGATIVE, 2, DESCENDING),
        rated_record("model", "y-00", Polarity.POSITIVE, 3),
        rated_record("other", "x-00", Polarity.POSITIVE, 3),
    )
    scores = question_scores(phrasing_values(records, FIVE), QUESTIONNAIRE, (MODEL,))[MODEL]

    profile = axis_profile(MODEL, AxisKey.X, records, scores, facet_scores(scores, QUESTIONNAIRE), QUESTIONNAIRE, FIVE)

    assert profile.ratings.answered == 4
    assert profile.ratings.ends_share == 0.5
    assert profile.scores == ScoreSplit(
        positive=1, negative=0, zero=0, mean_absolute=0.75, opposing_facets=0, facet_balanced=0.75, farthest=()
    )
    assert (profile.statements.one_sided, profile.statements.statements) == (2, 2)
    both = model_profile(MODEL, records, scores, (), QUESTIONNAIRE, FIVE)
    assert (both.x.ratings.answered, both.y.ratings.answered) == (4, 1)
