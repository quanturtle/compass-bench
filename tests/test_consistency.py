from collections.abc import Sequence
from itertools import product

import pytest

from compass_bench.domain.axis_pair import AxisKey, Polarity, PolarityPair
from compass_bench.domain.consistency import (
    AxisConsistency,
    Cell,
    LevelPosition,
    Spread,
    axis_consistency,
    cell_values,
    model_consistency,
    pooled_cells,
    variance_shares,
)
from compass_bench.domain.design.conditions import Condition, condition_id, cross
from compass_bench.domain.design.factors import DisplayOrder, NumericMapping
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.scoring import PhrasingKey, phrasing_values
from tests.builders.analysis import rated_record
from tests.builders.design import BOTH_FACTORS, build_condition
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis

SCALE = Scale(labels=FIVE_POINT_LABELS)
QUESTIONNAIRE = build_questionnaire(questions_per_axis(4), FIVE_POINT_LABELS)
MODEL = ModelId("model")
CONDITIONS = cross(BOTH_FACTORS, STANDARD_INSTRUCTION)
BY_ID = {condition.id: condition for condition in CONDITIONS}
ASCENDING = CONDITIONS[0]
DESCENDING = build_condition(DisplayOrder.DESCENDING, NumericMapping.AGREE_HIGH)
X_00 = QuestionId("x-00")


def answered(ratings: Sequence[tuple[str, Polarity, int]], condition: Condition = ASCENDING) -> tuple[TrialRecord, ...]:
    """The model rating each (question, phrasing) under `condition`."""
    return tuple(rated_record("model", question, polarity, rating, condition) for question, polarity, rating in ratings)


def agreeing(questions: int, rating: int) -> tuple[TrialRecord, ...]:
    """The model giving `rating` to both phrasings of the first `questions` x questions."""
    return answered([(f"x-{index:02d}", polarity, rating) for index in range(questions) for polarity in Polarity])


def consistency_of(records: Sequence[TrialRecord]) -> AxisConsistency:
    values = phrasing_values(records, SCALE)
    return axis_consistency(MODEL, AxisKey.X, values, cell_values(records, BY_ID, SCALE), QUESTIONNAIRE)


def cell(wording: str) -> Cell:
    return (DisplayOrder.ASCENDING, NumericMapping.AGREE_HIGH, wording)


def test_a_model_that_agrees_with_everything_leans_to_agree_and_is_consistent_on_no_question() -> None:
    result = consistency_of(agreeing(4, 4))

    assert result.poles == PolarityPair(negative=-0.5, positive=0.5)
    assert result.agreement_lean == 0.5
    assert (result.consistent_questions, result.midpoint_questions, result.same_side_questions) == (0, 0, 4)
    assert result.questions == 4
    # every question draws the same agreement from both statements, so neither side has spread
    assert result.pole_correlation is None


def test_a_positioned_model_shows_its_position_on_both_poles_and_opposed_agreement() -> None:
    # agreement with the positive statement rises across questions while agreement with the negative one falls
    records = answered(
        [
            ("x-00", Polarity.POSITIVE, 3),
            ("x-00", Polarity.NEGATIVE, 3),
            ("x-01", Polarity.POSITIVE, 4),
            ("x-01", Polarity.NEGATIVE, 2),
            ("x-02", Polarity.POSITIVE, 5),
            ("x-02", Polarity.NEGATIVE, 1),
            ("x-03", Polarity.POSITIVE, 4),
            ("x-03", Polarity.NEGATIVE, 2),
        ]
    )

    result = consistency_of(records)

    assert (result.poles.negative, result.poles.positive) == pytest.approx((0.5, 0.5))
    assert result.agreement_lean == pytest.approx(0.0)
    assert result.pole_correlation == pytest.approx(-1.0)
    # x-00 is rated 3 on both statements: at the midpoint, neither consistent nor on one side
    assert (result.consistent_questions, result.midpoint_questions, result.same_side_questions) == (3, 1, 0)
    assert result.questions == 4


def test_poles_are_undefined_without_answers_and_the_correlation_below_three_questions() -> None:
    one_question = consistency_of(answered([("x-00", Polarity.POSITIVE, 4), ("x-00", Polarity.NEGATIVE, 2)]))
    assert one_question.poles == PolarityPair(negative=0.5, positive=0.5)
    assert one_question.pole_correlation is None

    unanswered = axis_consistency(MODEL, AxisKey.Y, {}, {}, QUESTIONNAIRE)
    assert unanswered.poles == PolarityPair(negative=None, positive=None)
    assert (unanswered.agreement_lean, unanswered.spread, unanswered.questions) == (None, None, 0)


def test_spread_needs_two_cells_with_two_scored_questions_each() -> None:
    one_cell = agreeing(2, 4)
    assert consistency_of(one_cell).spread is None

    second_cell = answered(
        [
            ("x-00", Polarity.POSITIVE, 5),
            ("x-00", Polarity.NEGATIVE, 1),
            ("x-01", Polarity.POSITIVE, 5),
            ("x-01", Polarity.NEGATIVE, 1),
        ],
        DESCENDING,
    )

    result = consistency_of(one_cell + second_cell)

    assert result.spread == Spread(low=0.0, high=1.0, cells=2)
    assert result.unstable_questions == 0


def test_a_question_whose_score_changes_sign_between_cells_is_unstable() -> None:
    toward_positive = answered([("x-00", Polarity.POSITIVE, 5), ("x-00", Polarity.NEGATIVE, 1)])
    toward_negative = answered([("x-00", Polarity.POSITIVE, 1), ("x-00", Polarity.NEGATIVE, 5)], DESCENDING)

    assert consistency_of(toward_positive + toward_negative).unstable_questions == 1


def test_runs_with_one_and_three_wordings_pool_the_shared_wording_into_one_cell() -> None:
    key: PhrasingKey = (MODEL, X_00, Polarity.POSITIVE)
    one_wording = {cell("a"): {key: [0.5]}}
    three_wordings = {cell(wording): {key: [1.0]} for wording in ("a", "b", "c")}

    pooled = pooled_cells([one_wording, three_wordings])

    assert set(pooled) == {cell("a"), cell("b"), cell("c")}
    assert pooled[cell("a")] == {key: [0.5, 1.0]}


def test_model_consistency_covers_both_axes() -> None:
    records = answered([("y-00", Polarity.POSITIVE, 4), ("y-00", Polarity.NEGATIVE, 2)])

    result = model_consistency(
        MODEL, phrasing_values(records, SCALE), cell_values(records, BY_ID, SCALE), QUESTIONNAIRE
    )

    assert (result.x.questions, result.y.questions) == (0, 1)


def worded_condition(order: DisplayOrder, mapping: NumericMapping, wording: str) -> Condition:
    """A condition of a design whose instruction factor lists `wording`, so its id carries the wording as a label."""
    return Condition(
        id=condition_id(order, mapping, wording), display_order=order, numeric_mapping=mapping, instruction=wording
    )


def worded_consistency(records: Sequence[TrialRecord], conditions: Sequence[Condition]) -> AxisConsistency:
    by_id = {condition.id: condition for condition in conditions}
    values = phrasing_values(records, SCALE)
    return axis_consistency(MODEL, AxisKey.X, values, cell_values(records, by_id, SCALE), QUESTIONNAIRE)


def two_questions(ratings: PolarityPair[int], condition: Condition) -> tuple[TrialRecord, ...]:
    """Two questions answered under `condition`, each statement at its pole's rating."""
    return tuple(
        rated_record("model", question, polarity, ratings.get(polarity), condition)
        for question in ("x-00", "x-01")
        for polarity in Polarity
    )


def test_marginals_give_the_position_at_each_wording_and_layout_with_their_ranges() -> None:
    # rating 4 toward both poles cancels to 0; 5 toward the positive pole and 3 toward the negative one gives +0.5
    plain = [worded_condition(order, mapping, "plain") for order, mapping in product(DisplayOrder, NumericMapping)]
    shifted = worded_condition(DisplayOrder.ASCENDING, NumericMapping.AGREE_HIGH, "shifted")
    records = tuple(
        record for condition in plain for record in two_questions(PolarityPair(negative=4, positive=4), condition)
    ) + two_questions(PolarityPair(negative=3, positive=5), shifted)

    result = worded_consistency(records, [*plain, shifted]).marginals

    assert [(level.level, level.position, level.questions) for level in result.wordings] == [
        ("plain", 0.0, 2),
        ("shifted", 0.5, 2),
    ]
    assert result.wording_range == 0.5
    assert [level.level for level in result.layouts] == [
        "ascending.agree_high",
        "ascending.agree_low",
        "descending.agree_high",
        "descending.agree_low",
    ]
    assert [level.position for level in result.layouts] == [0.25, 0.0, 0.0, 0.0]
    assert result.layout_range == 0.25
    # each answer counts once, so the shifted cell is one of three ascending cells and one of three agree_high cells
    assert [level.position for level in result.display_orders] == pytest.approx([1 / 6, 0.0])
    assert [level.position for level in result.numeric_mappings] == pytest.approx([1 / 6, 0.0])


def test_a_level_position_is_undefined_below_two_scored_questions() -> None:
    result = consistency_of(answered([("x-00", Polarity.POSITIVE, 4), ("x-00", Polarity.NEGATIVE, 2)])).marginals

    assert result.wordings == (LevelPosition(level=STANDARD_INSTRUCTION, position=None, questions=1),)
    assert (result.wording_range, result.layout_range) == (None, None)


def test_variance_shares_split_a_display_order_shift_from_a_wording_shift() -> None:
    # descending layouts answer one point higher toward the positive pole, and wording b half a point
    positions = {
        (order, mapping, wording): (1.0 if order is DisplayOrder.DESCENDING else 0.0) + (0.5 if wording == "b" else 0.0)
        for order, mapping, wording in product(DisplayOrder, NumericMapping, ("a", "b"))
    }

    shares = variance_shares(positions)

    assert shares is not None
    assert (shares.display_order, shares.wording, shares.numeric_mapping) == pytest.approx((0.8, 0.2, 0.0))
    assert shares.residual == pytest.approx(0.0)
    assert shares.cells == 8


def test_variance_shares_need_a_full_grid_with_spread() -> None:
    partial_grid = {cell("a"): 0.0, (DisplayOrder.DESCENDING, NumericMapping.AGREE_LOW, "b"): 1.0}
    flat_grid = {cell("a"): 0.5, cell("b"): 0.5}

    assert variance_shares(partial_grid) is None
    assert variance_shares(flat_grid) is None
    assert variance_shares({cell("a"): 0.5}) is None
