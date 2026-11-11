"""Pearson's correlation between two paired samples, from the standard library."""

from collections.abc import Sequence
from statistics import StatisticsError, correlation
from typing import Final

MIN_PAIRS: Final = 3


class UnpairedValues(Exception):
    """The two samples differ in length, so their values are not paired."""


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson's r over the pairs; None below three pairs or when either sample has no spread."""
    if len(xs) != len(ys):
        raise UnpairedValues(f"{len(xs)} values are paired with {len(ys)}")
    if len(xs) < MIN_PAIRS:
        return None
    try:
        return correlation(xs, ys)
    except StatisticsError:
        return None
