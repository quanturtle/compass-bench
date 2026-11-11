"""Sign stability of a pair's gap across the cells it was asked in."""

from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.consistency import cell_values
from compass_bench.domain.design.conditions import cross
from compass_bench.domain.design.experiment import AnalysisSettings
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from compass_bench.domain.ids import ModelId
from compass_bench.domain.inference import pair_axes
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.robustness import OrderingRobustness, ordering_robustness, pair_robustness
from compass_bench.domain.scoring import phrasing_values, question_scores
from tests.builders.analysis import pair_axis, rated_record
from tests.builders.design import BOTH_FACTORS
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis

QUESTIONNAIRE = build_questionnaire(questions_per_axis(3), FIVE_POINT_LABELS)
SCALE = QUESTIONNAIRE.scale
CONDITIONS = cross(BOTH_FACTORS, STANDARD_INSTRUCTION)
BY_ID = {condition.id: condition for condition in CONDITIONS}
SETTINGS = AnalysisSettings(confidence_level=0.95, coverage_floor=0.8, equivalence_margin=0.1)


def cell_records(model: str, positive: int, negative: int, condition_index: int) -> tuple[TrialRecord, ...]:
    condition = CONDITIONS[condition_index]
    return tuple(
        rated_record(model, question, polarity, positive if polarity is Polarity.POSITIVE else negative, condition)
        for question in ("x-00", "x-01", "x-02")
        for polarity in Polarity
    )


def test_a_gap_with_one_sign_in_every_cell_keeps_it_in_all_of_them() -> None:
    # `high` agrees toward the positive pole in every cell, `low` toward the negative pole
    records = tuple(
        record
        for index in range(len(CONDITIONS))
        for record in cell_records("high", 5, 1, index) + cell_records("low", 1, 5, index)
    )
    values = phrasing_values(records, SCALE)
    scores = question_scores(values, QUESTIONNAIRE, (ModelId("high"), ModelId("low")))
    ((pair, axes),) = pair_axes(scores, SETTINGS).items()

    robustness = pair_robustness(pair[0], pair[1], axes, cell_values(records, BY_ID, SCALE), QUESTIONNAIRE)

    assert robustness.x == OrderingRobustness(cells=4, same_sign=4)
    # no y questions were asked, so the y gap is not estimable
    assert robustness.y is None


def test_a_cell_whose_gap_opposes_the_headline_is_counted_against_it() -> None:
    records = (
        *cell_records("high", 5, 1, 0),
        *cell_records("low", 1, 5, 0),
        *cell_records("high", 5, 1, 1),
        *cell_records("low", 1, 5, 1),
        # the third cell reverses the two models
        *cell_records("high", 1, 5, 2),
        *cell_records("low", 5, 1, 2),
    )
    values = phrasing_values(records, SCALE)
    scores = question_scores(values, QUESTIONNAIRE, (ModelId("high"), ModelId("low")))
    ((pair, axes),) = pair_axes(scores, SETTINGS).items()

    robustness = pair_robustness(pair[0], pair[1], axes, cell_values(records, BY_ID, SCALE), QUESTIONNAIRE)

    assert robustness.x == OrderingRobustness(cells=3, same_sign=2)


def test_a_zero_or_inestimable_headline_gap_has_no_sign_to_keep() -> None:
    assert ordering_robustness(pair_axis(-0.1, 0.1, questions=10, p_holm=1.0), [0.2, 0.3]) is None
