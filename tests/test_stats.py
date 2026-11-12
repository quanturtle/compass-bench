import math
from statistics import stdev

import pytest
from scipy import stats

from compass_bench.domain.stats.corrections import bonferroni_level, holm
from compass_bench.domain.stats.correlation import UnpairedValues, pearson
from compass_bench.domain.stats.icc import ReliabilityBand, icc_consistency, icc_one_way, reliability_band
from compass_bench.domain.stats.student_t import (
    TooFewValues,
    equivalence_p_value,
    equivalence_power,
    mean_interval,
    minimum_detectable_mean,
    standardized_mean,
    zero_mean_p_value,
)

# Student's t quantile at 0.975 with 2 degrees of freedom, from published tables
T_975_2: float = 4.302653


def test_the_interval_is_the_mean_plus_or_minus_t_standard_errors() -> None:
    mean, low, high = mean_interval((1.0, 2.0, 3.0), level=0.95)

    half_width = T_975_2 / math.sqrt(3)
    assert (mean, low, high) == pytest.approx((2.0, 2.0 - half_width, 2.0 + half_width), rel=1e-6)


def test_the_p_value_matches_the_one_sample_t_test() -> None:
    values = (0.4, -0.1, 0.3, 0.2, 0.5)

    assert zero_mean_p_value(values) == pytest.approx(stats.ttest_1samp(values, 0.0).pvalue)


def test_zero_spread_gives_a_point_interval_and_a_p_value_of_one_or_zero() -> None:
    assert mean_interval((0.5, 0.5), level=0.95) == (0.5, 0.5, 0.5)
    assert (zero_mean_p_value((0.0, 0.0)), zero_mean_p_value((0.5, 0.5))) == (1.0, 0.0)


def test_the_standardized_mean_is_the_mean_over_the_standard_deviation_and_undefined_without_spread() -> None:
    assert standardized_mean((1.0, 3.0, 5.0)) == pytest.approx(1.5)
    assert standardized_mean((0.0, 0.5, 1.0)) == pytest.approx(1.0)
    assert standardized_mean((0.5, 0.5)) is None


def test_values_equal_up_to_float_rounding_have_zero_spread() -> None:
    values = (0.3, 0.1 + 0.2, 0.3)

    assert standardized_mean(values) is None
    assert zero_mean_p_value(values) == 0.0


def test_a_single_value_has_no_t_statistic() -> None:
    with pytest.raises(TooFewValues, match="at least 2 values, not 1"):
        mean_interval((0.5,), level=0.95)
    with pytest.raises(TooFewValues):
        minimum_detectable_mean((0.5,), level=0.95, power=0.8)
    with pytest.raises(TooFewValues):
        equivalence_p_value((0.5,), margin=0.1)


def test_the_minimum_detectable_mean_adds_the_power_quantile_to_the_test_quantile() -> None:
    # sample standard deviation 1 over three values, so the standard error is 1 / sqrt(3)
    detectable = minimum_detectable_mean((1.0, 2.0, 3.0), level=0.95, power=0.8)

    assert detectable == pytest.approx((T_975_2 + stats.t.ppf(0.8, 2)) / math.sqrt(3), rel=1e-6)
    assert minimum_detectable_mean((0.5, 0.5), level=0.95, power=0.8) == 0.0


def test_the_equivalence_p_value_is_the_larger_of_the_two_one_sided_tests() -> None:
    values = (0.01, -0.02, 0.03, 0.0, 0.02)

    above = stats.ttest_1samp(values, -0.1, alternative="greater").pvalue
    below = stats.ttest_1samp(values, 0.1, alternative="less").pvalue
    assert equivalence_p_value(values, margin=0.1) == pytest.approx(max(above, below))
    assert equivalence_p_value((0.5, 0.6, 0.4), margin=0.1) > 0.98


def test_the_equivalence_power_at_a_zero_gap_is_the_noncentral_t_mass_the_two_tests_leave() -> None:
    # 33 gaps spread 0.19, the spread METHODOLOGY names for 80% power at the 0.1 margin
    quantiles = [float(stats.norm.ppf((index + 0.5) / 33)) for index in range(33)]
    gaps = [quantile * 0.19 / stdev(quantiles) for quantile in quantiles]

    power = equivalence_power(gaps, margin=0.1, alpha=0.05)

    critical = stats.t.ppf(0.95, 32)
    assert power == pytest.approx(1 - 2 * stats.nct.cdf(critical, 32, 0.1 / (0.19 / math.sqrt(33))))
    assert 0.8 < power < 0.82
    assert equivalence_power([gap * 2 for gap in gaps], margin=0.1, alpha=0.05) < 0.01
    assert equivalence_power((0.5, 0.5), margin=0.1, alpha=0.05) == 1.0


def test_zero_spread_is_equivalent_only_inside_the_margin() -> None:
    assert equivalence_p_value((0.05, 0.05), margin=0.1) == 0.0
    assert (equivalence_p_value((0.1, 0.1), margin=0.1), equivalence_p_value((0.5, 0.5), margin=0.1)) == (1.0, 1.0)


def test_pearson_is_signed_and_scale_free() -> None:
    assert pearson((1.0, 2.0, 3.0), (2.0, 4.0, 6.0)) == pytest.approx(1.0)
    assert pearson((1.0, 2.0, 3.0), (3.0, 2.0, 1.0)) == pytest.approx(-1.0)
    assert pearson((1.0, 2.0, 3.0, 4.0), (1.0, 3.0, 2.0, 4.0)) == pytest.approx(0.8)


def test_pearson_is_undefined_below_three_pairs_or_without_spread() -> None:
    assert pearson((1.0, 2.0), (1.0, 2.0)) is None
    assert pearson((1.0, 2.0, 3.0), (0.5, 0.5, 0.5)) is None


def test_pearson_rejects_samples_of_different_lengths() -> None:
    with pytest.raises(UnpairedValues, match="3 values are paired with 2"):
        pearson((1.0, 2.0, 3.0), (1.0, 2.0))


def test_holm_caps_an_adjusted_p_at_one() -> None:
    assert holm({"a": 0.6, "b": 0.7}) == pytest.approx({"a": 1.0, "b": 1.0})


def test_bonferroni_splits_the_miss_rate_across_the_family() -> None:
    assert bonferroni_level(0.95, 2) == pytest.approx(0.975)


def test_holm_multiplies_by_the_remaining_family_and_keeps_the_adjusted_values_in_order() -> None:
    adjusted = holm({"a": 0.01, "b": 0.04, "c": 0.03, "untestable": 1.0})

    # sorted a, c, b, untestable: 4 x 0.01, 3 x 0.03, then b's 2 x 0.04 = 0.08 rises to c's 0.09
    assert adjusted == pytest.approx({"a": 0.04, "b": 0.09, "c": 0.09, "untestable": 1.0})


def test_icc_one_way_is_one_for_identical_groups_zero_within_and_undefined_without_groups_or_spread() -> None:
    assert icc_one_way([[5.0, 5.0], [1.0, 1.0]]) == pytest.approx(1.0)
    crossed = icc_one_way([[5.0, 1.0], [1.0, 5.0]])
    assert crossed is not None and crossed < 0
    assert icc_one_way([[5.0, 4.0]]) is None
    assert icc_one_way([[3.0, 3.0], [3.0, 3.0]]) is None
    assert icc_one_way([[5.0], [1.0]]) is None


def test_icc_consistency_ignores_a_shift_between_columns_and_needs_two_rows_and_columns() -> None:
    rows = [[0.1, 0.3], [0.5, 0.7], [-0.2, 0.0], [0.9, 1.1]]
    assert icc_consistency(rows) == pytest.approx(1.0)
    disagreeing = icc_consistency([[0.1, 0.9], [0.5, -0.5], [-0.2, 0.3]])
    assert disagreeing is not None and disagreeing < 1.0
    assert icc_consistency([[0.1, 0.3]]) is None
    assert icc_consistency([[0.1], [0.5]]) is None
    assert icc_consistency([[0.1, 0.3], [0.5]]) is None
    assert icc_consistency([[0.5, 0.5], [0.5, 0.5]]) is None


def test_icc_consistency_is_undefined_when_every_row_holds_the_same_values() -> None:
    assert icc_consistency([[1.0, 1.1, 1.2]] * 5) is None
    nearly = icc_consistency([[1.0, 1.1, 1.2]] * 4 + [[1.0, 1.1, 1.3]])
    assert nearly is not None and nearly < 1.0


def test_the_reliability_band_follows_koo_and_li() -> None:
    assert [reliability_band(value) for value in (0.2, 0.5, 0.75, 0.9)] == [
        ReliabilityBand.POOR,
        ReliabilityBand.MODERATE,
        ReliabilityBand.GOOD,
        ReliabilityBand.EXCELLENT,
    ]
