"""Intraclass correlations: ICC(1) over groups of answers, and ICC(3,1) over targets rated in several runs."""

from collections.abc import Sequence
from enum import StrEnum
from statistics import fmean


class ReliabilityBand(StrEnum):
    """Koo and Li's (2016) bands: below 0.5, 0.5 to 0.75, 0.75 to 0.9, and above 0.9. They read an absolute-agreement
    ICC's 95% interval on them; the point estimate of the consistency form is read here."""

    POOR = "poor"
    MODERATE = "moderate"
    GOOD = "good"
    EXCELLENT = "excellent"


def reliability_band(icc: float) -> ReliabilityBand:
    if icc < 0.5:
        return ReliabilityBand.POOR
    if icc < 0.75:
        return ReliabilityBand.MODERATE
    if icc < 0.9:
        return ReliabilityBand.GOOD
    return ReliabilityBand.EXCELLENT


def icc_one_way(groups: Sequence[Sequence[float]]) -> float | None:
    """ICC(1): the share of the variance that lies between the groups, under one-way random effects.

    Groups may differ in size. None below two groups, when no group has two values, or without any spread."""
    groups = [group for group in groups if group]
    total = sum(len(group) for group in groups)
    if len(groups) < 2 or total <= len(groups):
        return None
    grand = fmean(value for group in groups for value in group)
    between = sum(len(group) * (fmean(group) - grand) ** 2 for group in groups) / (len(groups) - 1)
    within = sum((value - fmean(group)) ** 2 for group in groups for value in group) / (total - len(groups))
    mean_size = (total - sum(len(group) ** 2 for group in groups) / total) / (len(groups) - 1)
    denominator = between + (mean_size - 1) * within
    if denominator == 0:
        return None
    return (between - within) / denominator


def icc_consistency(rows: Sequence[Sequence[float]]) -> float | None:
    """ICC(3,1): each row is one target rated once in each of the same k columns; consistency, single measure.

    None below two rows or two columns, or without any spread."""
    if len(rows) < 2 or len(rows[0]) < 2 or any(len(row) != len(rows[0]) for row in rows):
        return None
    n, k = len(rows), len(rows[0])
    grand = fmean(value for row in rows for value in row)
    row_means = [fmean(row) for row in rows]
    column_means = [fmean(row[column] for row in rows) for column in range(k)]
    rows_squares = k * sum((mean - grand) ** 2 for mean in row_means)
    columns_squares = n * sum((mean - grand) ** 2 for mean in column_means)
    total_squares = sum((value - grand) ** 2 for row in rows for value in row)
    if total_squares == 0:
        return None
    # rounding leaves sums of squares near 1e-16 of the total where they are exactly 0
    tolerance = 1e-12 * total_squares
    rows_squares = rows_squares if rows_squares >= tolerance else 0.0
    residual = total_squares - rows_squares - columns_squares
    residual = residual if residual >= tolerance else 0.0
    mean_rows = rows_squares / (n - 1)
    mean_error = residual / ((n - 1) * (k - 1))
    denominator = mean_rows + (k - 1) * mean_error
    if denominator == 0:
        return None
    return (mean_rows - mean_error) / denominator
