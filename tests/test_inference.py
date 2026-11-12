from statistics import fmean, stdev

import pytest

from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.claims import significance_reasons
from compass_bench.domain.design.experiment import AnalysisSettings
from compass_bench.domain.ids import ModelId
from compass_bench.domain.inference import (
    Bounded,
    EstimateKind,
    NotEstimable,
    axis_position,
    estimate,
    opposed_gaps,
    pair_axes,
    paired_gaps,
)
from compass_bench.domain.stats.correlation import pearson
from compass_bench.domain.stats.student_t import equivalence_p_value, zero_mean_p_value
from tests.builders.analysis import scores_on

SETTINGS = AnalysisSettings(confidence_level=0.95, coverage_floor=0.8, equivalence_margin=0.1)
FIRST = scores_on(AxisKey.X, (0.1, 0.4, 0.2, 0.5)) + scores_on(AxisKey.Y, (0.0, -0.2))
SECOND = scores_on(AxisKey.X, (-0.3, 0.1, -0.2, 0.0, 0.9)) + scores_on(AxisKey.Y, (0.3,))


def test_reversing_a_pair_negates_its_gaps_and_mirrors_the_interval_with_the_same_p() -> None:
    forward, backward = paired_gaps(FIRST, SECOND, AxisKey.X), paired_gaps(SECOND, FIRST, AxisKey.X)
    ahead, behind = estimate(forward, 0.95), estimate(backward, 0.95)

    assert backward == tuple(-gap for gap in forward)
    assert isinstance(ahead, Bounded) and isinstance(behind, Bounded)
    assert (behind.point, behind.low, behind.high) == pytest.approx((-ahead.point, -ahead.high, -ahead.low))
    assert zero_mean_p_value(backward) == pytest.approx(zero_mean_p_value(forward))


def test_a_position_holds_jointly_across_both_axes_and_one_question_is_not_estimable() -> None:
    x = axis_position(FIRST, AxisKey.X, coverage=1.0, settings=SETTINGS)
    y = axis_position(SECOND, AxisKey.Y, coverage=1.0, settings=SETTINGS)

    assert isinstance(x.estimate, Bounded) and x.estimate.level == pytest.approx(0.975)
    assert y.estimate == NotEstimable(kind=EstimateKind.NOT_ESTIMABLE, questions=1)


def test_pairs_come_in_model_id_order_and_an_untestable_gap_enters_holm_at_one() -> None:
    pairs = pair_axes({ModelId("second"): SECOND, ModelId("first"): FIRST}, SETTINGS)

    (pair,) = pairs
    x, y = pairs[pair].x, pairs[pair].y
    assert pair == (ModelId("first"), ModelId("second"))
    assert (y.p_raw, y.p_holm) == (1.0, 1.0)
    assert x.p_holm == pytest.approx(min(1.0, 2 * x.p_raw))


def test_scores_equal_in_exact_arithmetic_but_averaged_from_other_cells_do_not_pass_the_ordering_gate() -> None:
    # both are -5/6 on a 4-point scale's values, averaged as the scoring does; the floats differ in the last digit
    third = 1 / 3
    one_way = fmean((fmean((-1.0, -1.0, -1.0, -1.0)), fmean((-1.0, -1.0, -1.0, third))))
    other_way = fmean((fmean((-1.0, -1.0, -1.0, -third)), fmean((-1.0, -1.0, -1.0, -third))))
    level = scores_on(AxisKey.Y, (0.0, 0.0))
    first = scores_on(AxisKey.X, (one_way,) * 20) + level
    second = scores_on(AxisKey.X, (other_way,) * 10 + (one_way,) * 10) + level

    pairs = pair_axes({ModelId("first"): first, ModelId("second"): second}, SETTINGS)

    (pair,) = pairs
    x = pairs[pair].x
    assert one_way != other_way
    assert (x.p_raw, x.p_holm, x.d_z) == (1.0, 1.0, None)
    assert significance_reasons(x, AxisKey.X, alpha=0.05) != ()


def test_a_pairs_d_z_is_its_mean_gap_over_the_gaps_standard_deviation_and_undefined_below_two_gaps() -> None:
    pairs = pair_axes({ModelId("first"): FIRST, ModelId("second"): SECOND}, SETTINGS)
    gaps = paired_gaps(FIRST, SECOND, AxisKey.X)

    (pair,) = pairs
    assert pairs[pair].x.d_z == pytest.approx(fmean(gaps) / stdev(gaps))
    assert pairs[pair].y.d_z is None


def test_a_pair_reports_the_correlation_of_the_shared_scores_and_the_questions_opposing_the_gap() -> None:
    pairs = pair_axes({ModelId("first"): FIRST, ModelId("second"): SECOND}, SETTINGS)

    (pair,) = pairs
    # shared x questions: first (0.1, 0.4, 0.2, 0.5) against second (-0.3, 0.1, -0.2, 0.0); every gap is negative
    assert pairs[pair].x.correlation == pytest.approx(pearson((0.1, 0.4, 0.2, 0.5), (-0.3, 0.1, -0.2, 0.0)))
    assert pairs[pair].x.opposed_questions == 0
    assert (pairs[pair].y.correlation, pairs[pair].y.opposed_questions) == (None, None)


def test_equivalence_p_values_form_their_own_holm_family_and_an_untestable_gap_enters_at_one() -> None:
    pairs = pair_axes({ModelId("first"): FIRST, ModelId("second"): SECOND}, SETTINGS)
    gaps = paired_gaps(FIRST, SECOND, AxisKey.X)

    (pair,) = pairs
    x, y = pairs[pair].x, pairs[pair].y
    assert x.p_equivalence_raw == pytest.approx(equivalence_p_value(gaps, SETTINGS.equivalence_margin))
    assert x.p_equivalence_holm == pytest.approx(min(1.0, 2 * x.p_equivalence_raw))
    assert (y.p_equivalence_raw, y.p_equivalence_holm) == (1.0, 1.0)


def test_opposed_gaps_count_the_minority_sign_and_are_undefined_without_a_direction() -> None:
    assert opposed_gaps((1.0, 1.0, -1.0)) == 1
    assert opposed_gaps((0.5, -0.5)) is None
    assert opposed_gaps((0.5,)) is None


def test_a_gaps_detectable_effect_at_the_familys_first_step_exceeds_its_own_and_grows_with_the_family() -> None:
    first, second = ModelId("first"), ModelId("second")
    third = scores_on(AxisKey.X, (0.0, 0.2, 0.1, 0.3)) + scores_on(AxisKey.Y, (0.1, 0.1))
    two_models = pair_axes({first: FIRST, second: SECOND}, SETTINGS)
    three_models = pair_axes({first: FIRST, second: SECOND, ModelId("third"): third}, SETTINGS)

    alone = two_models[(first, second)].x
    crowded = three_models[(first, second)].x

    assert isinstance(alone.gap, Bounded)
    assert (alone.family_size, crowded.family_size) == (2, 6)
    assert alone.minimum_detectable_family is not None and crowded.minimum_detectable_family is not None
    assert alone.gap.minimum_detectable < alone.minimum_detectable_family < crowded.minimum_detectable_family
    assert two_models[(first, second)].y.minimum_detectable_family is None


def test_the_minimum_detectable_mean_exceeds_the_intervals_half_width() -> None:
    position = axis_position(FIRST, AxisKey.X, coverage=1.0, settings=SETTINGS)

    assert isinstance(position.estimate, Bounded)
    half_width = (position.estimate.high - position.estimate.low) / 2
    assert position.estimate.minimum_detectable > half_width
