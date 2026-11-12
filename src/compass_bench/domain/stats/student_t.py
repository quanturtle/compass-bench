"""Student's t over a sample of question scores or question-by-question gaps, from scipy.stats."""

import math
from collections.abc import Sequence
from statistics import fmean, stdev
from typing import Final

from scipy import stats

# a deviation at or below this share of the largest |value| comes from float rounding, not from the values
ROUNDING_SPREAD: Final = 1e-12


class TooFewValues(Exception):
    """A t statistic needs at least two values to have a spread."""


def spread(values: Sequence[float]) -> tuple[float, float]:
    """The mean and the sample standard deviation; raises TooFewValues below two values.
    A deviation within ROUNDING_SPREAD of the largest |value| is float rounding and reads as 0."""
    if len(values) < 2:
        raise TooFewValues(f"a t statistic needs at least 2 values, not {len(values)}")
    deviation = stdev(values)
    largest = max(abs(value) for value in values)
    return fmean(values), deviation if deviation > ROUNDING_SPREAD * largest else 0.0


def t_quantile(level: float, degrees: int) -> float:
    """The two-sided t critical value at `level` with `degrees` degrees of freedom."""
    return float(stats.t.ppf((1 + level) / 2, degrees))


def mean_interval(values: Sequence[float], level: float) -> tuple[float, float, float]:
    """The mean and its two-sided t-interval at `level`, with len(values) - 1 degrees of freedom.

    Needs at least two values; with zero spread, both ends equal the mean."""
    mean, deviation = spread(values)
    half_width = float(stats.t.ppf((1 + level) / 2, len(values) - 1)) * deviation / math.sqrt(len(values))
    return mean, mean - half_width, mean + half_width


def standardized_mean(values: Sequence[float]) -> float | None:
    """The mean over the sample standard deviation; on question-by-question gaps it is Cohen's d_z.

    None with zero spread, where the ratio is undefined."""
    mean, deviation = spread(values)
    return mean / deviation if deviation > 0 else None


def zero_mean_p_value(values: Sequence[float]) -> float:
    """Two-sided one-sample t-test that the mean is 0; on question-by-question gaps it is the paired test.

    With zero spread, p is 1 when the mean is 0 and 0 otherwise."""
    mean, deviation = spread(values)
    if deviation == 0:
        return 1.0 if mean == 0 else 0.0
    statistic = mean / (deviation / math.sqrt(len(values)))
    return float(2 * stats.t.sf(abs(statistic), len(values) - 1))


def minimum_detectable_mean(values: Sequence[float], level: float, power: float) -> float:
    """The smallest |mean| the two-sided t-test at `level` would detect with probability `power`, given this spread.

    (t at (1 + level) / 2 plus t at `power`, both with n - 1 degrees of freedom) times the standard error; 0 with
    zero spread."""
    _, deviation = spread(values)
    degrees = len(values) - 1
    quantiles = float(stats.t.ppf((1 + level) / 2, degrees)) + float(stats.t.ppf(power, degrees))
    return quantiles * deviation / math.sqrt(len(values))


def equivalence_power(values: Sequence[float], margin: float, alpha: float) -> float:
    """The power of the two one-sided tests at `alpha` to show a true mean of 0 within ±margin, given this spread.

    1 minus twice the noncentral t's mass below the one-sided critical value, with noncentrality margin over the
    standard error: exact when the standard error is at most the margin over the critical value, else a lower
    bound, floored at 0 (Lakens, 2017). 1 with zero spread."""
    _, deviation = spread(values)
    if deviation == 0:
        return 1.0
    degrees = len(values) - 1
    critical = float(stats.t.ppf(1 - alpha, degrees))
    noncentrality = margin / (deviation / math.sqrt(len(values)))
    return max(0.0, 1 - 2 * float(stats.nct.cdf(critical, degrees, noncentrality)))


def equivalence_p_value(values: Sequence[float], margin: float) -> float:
    """Two one-sided t-tests that the mean lies within (-margin, margin): the larger of the two p-values.

    With zero spread, p is 0 when |mean| is below the margin and 1 otherwise."""
    mean, deviation = spread(values)
    if deviation == 0:
        return 0.0 if abs(mean) < margin else 1.0
    error = deviation / math.sqrt(len(values))
    degrees = len(values) - 1
    above_lower = float(stats.t.sf((mean + margin) / error, degrees))
    below_upper = float(stats.t.cdf((mean - margin) / error, degrees))
    return max(above_lower, below_upper)
