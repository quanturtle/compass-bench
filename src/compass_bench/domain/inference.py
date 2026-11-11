"""Positions and pair gaps: t-intervals and paired t-tests over question scores."""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import combinations
from statistics import fmean
from typing import Annotated, Final, Literal

from pydantic import Field

from compass_bench.domain.axis_pair import AxisKey, AxisPair
from compass_bench.domain.design.experiment import AnalysisSettings
from compass_bench.domain.ids import ModelId
from compass_bench.domain.scoring import QuestionScore
from compass_bench.domain.stats.corrections import bonferroni_level, holm
from compass_bench.domain.stats.correlation import pearson
from compass_bench.domain.stats.student_t import (
    equivalence_p_value,
    equivalence_power,
    mean_interval,
    minimum_detectable_mean,
    standardized_mean,
    zero_mean_p_value,
)
from compass_bench.domain.value import Value

# the power at which minimum_detectable is stated
POWER: Final = 0.8


class EstimateKind(StrEnum):
    BOUNDED = "bounded"
    NOT_ESTIMABLE = "not_estimable"


class Bounded(Value):
    """A mean over `questions` question scores or gaps, with its t-interval at confidence `level`.

    `minimum_detectable` is the smallest |mean| the test at `level` would find with 80% power, given this spread."""

    kind: Literal[EstimateKind.BOUNDED]
    point: float
    low: float
    high: float
    level: float
    questions: int
    minimum_detectable: float


class NotEstimable(Value):
    """Fewer than two questions, so there is no spread and no interval."""

    kind: Literal[EstimateKind.NOT_ESTIMABLE]
    questions: int


type Estimate = Annotated[Bounded | NotEstimable, Field(discriminator="kind")]


class AxisPosition(Value):
    """A model on one axis: the mean of its question scores, and the share of its trials there that were answered."""

    estimate: Estimate
    coverage: float


class PairAxis(Value):
    """The second model minus the first on one axis, over the questions both scored, with the paired t-test.

    The gap's interval is at confidence_level, unadjusted. A gap that is not estimable enters Holm at p = 1.
    `p_equivalence_raw` is the two one-sided tests' p that the gap lies within the equivalence margin, and
    `p_equivalence_holm` its Holm adjustment over every pair and axis as a family of its own.
    `d_z` is the mean gap over the gaps' standard deviation; None below two gaps or when every gap is equal.
    `correlation` is Pearson's r between the two models' scores on the shared questions; None below three or
    without spread. `opposed_questions` counts shared questions whose gap opposes the mean gap's sign; None when
    the gap is not estimable or its mean is 0. `family_size` is the number of gaps Holm adjusts together, and
    `minimum_detectable_family` the smallest |gap| the test at the family's first step, alpha over that size,
    would detect with 80% power; None when the gap is not estimable. `equivalence_power` is the power of the
    two one-sided tests at alpha, unadjusted, to show a true gap of 0 within the margin, given the observed
    spread; None when the gap is not estimable."""

    gap: Estimate
    d_z: float | None
    correlation: float | None
    opposed_questions: int | None
    p_raw: float
    p_holm: float
    p_equivalence_raw: float
    p_equivalence_holm: float
    family_size: int
    minimum_detectable_family: float | None
    equivalence_power: float | None


def estimate(values: Sequence[float], level: float) -> Estimate:
    """The mean with its t-interval at `level`, or NotEstimable below two values."""
    if len(values) < 2:
        return NotEstimable(kind=EstimateKind.NOT_ESTIMABLE, questions=len(values))
    point, low, high = mean_interval(values, level)
    return Bounded(
        kind=EstimateKind.BOUNDED,
        point=point,
        low=low,
        high=high,
        level=level,
        questions=len(values),
        minimum_detectable=minimum_detectable_mean(values, level, POWER),
    )


def position_level(settings: AnalysisSettings) -> float:
    """Each axis interval's level: bonferroni_level(confidence_level, 2), so the two axes hold jointly."""
    return bonferroni_level(settings.confidence_level, len(AxisKey))


def axis_position(
    scores: Sequence[QuestionScore], axis: AxisKey, coverage: float, settings: AnalysisSettings
) -> AxisPosition:
    values = [score.score for score in scores if score.axis is axis]
    return AxisPosition(estimate=estimate(values, position_level(settings)), coverage=coverage)


def shared_scores(
    first: Sequence[QuestionScore], second: Sequence[QuestionScore], axis: AxisKey
) -> tuple[tuple[float, float], ...]:
    """Both models' scores, question by question, over the questions both scored on the axis."""
    second_scores = {score.question: score.score for score in second if score.axis is axis}
    return tuple(
        (score.score, second_scores[score.question])
        for score in first
        if score.axis is axis and score.question in second_scores
    )


def paired_gaps(first: Sequence[QuestionScore], second: Sequence[QuestionScore], axis: AxisKey) -> tuple[float, ...]:
    """Second minus first, question by question, over the questions both models scored on the axis."""
    return tuple(theirs - ours for ours, theirs in shared_scores(first, second, axis))


def score_correlation(first: Sequence[QuestionScore], second: Sequence[QuestionScore], axis: AxisKey) -> float | None:
    shared = shared_scores(first, second, axis)
    return pearson([ours for ours, _ in shared], [theirs for _, theirs in shared])


def gap_d_z(gaps: Sequence[float]) -> float | None:
    """Cohen's d_z of the gaps, or None when fewer than two gaps leave it undefined."""
    return standardized_mean(gaps) if len(gaps) >= 2 else None


def opposed_gaps(gaps: Sequence[float]) -> int | None:
    """Gaps whose sign opposes the mean gap's; None below two gaps or when the mean gap is 0."""
    if len(gaps) < 2:
        return None
    mean = fmean(gaps)
    if mean == 0:
        return None
    return sum(gap * mean < 0 for gap in gaps)


def raw_p_value(gaps: Sequence[float]) -> float:
    """The paired t-test's p, or 1 when fewer than two gaps leave it untestable."""
    return zero_mean_p_value(gaps) if len(gaps) >= 2 else 1.0


def raw_equivalence_p_value(gaps: Sequence[float], margin: float) -> float:
    """The two one-sided tests' p that the mean gap lies within the margin, or 1 below two gaps."""
    return equivalence_p_value(gaps, margin) if len(gaps) >= 2 else 1.0


def power_at_zero_gap(gaps: Sequence[float], margin: float, level: float) -> float | None:
    """The equivalence tests' power at a true gap of 0, at alpha = 1 - level; None below two gaps."""
    return equivalence_power(gaps, margin, 1 - level) if len(gaps) >= 2 else None


def family_detectable(gaps: Sequence[float], level: float, family_size: int) -> float | None:
    """The detectable gap at Holm's first step: the two-sided test at alpha / family_size; None below two gaps."""
    if len(gaps) < 2:
        return None
    return minimum_detectable_mean(gaps, 1 - (1 - level) / family_size, POWER)


def pair_axes(
    scores: Mapping[ModelId, Sequence[QuestionScore]], settings: AnalysisSettings
) -> Mapping[tuple[ModelId, ModelId], AxisPair[PairAxis]]:
    """Every pair in canonical model-id order; Holm adjusts all pairs' p-values on both axes as one family.

    Holm runs before any PairAxis is built, so no p_holm is filled in later."""
    pairs = list(combinations(sorted(scores), 2))
    gaps = {(pair, axis): paired_gaps(scores[pair[0]], scores[pair[1]], axis) for pair in pairs for axis in AxisKey}
    p_raw = {key: raw_p_value(pair_gaps) for key, pair_gaps in gaps.items()}
    p_holm = holm(p_raw)
    p_equivalence_raw = {
        key: raw_equivalence_p_value(pair_gaps, settings.equivalence_margin) for key, pair_gaps in gaps.items()
    }
    p_equivalence_holm = holm(p_equivalence_raw)
    results = {
        (pair, axis): PairAxis(
            gap=estimate(gaps[(pair, axis)], settings.confidence_level),
            d_z=gap_d_z(gaps[(pair, axis)]),
            correlation=score_correlation(scores[pair[0]], scores[pair[1]], axis),
            opposed_questions=opposed_gaps(gaps[(pair, axis)]),
            p_raw=p_raw[(pair, axis)],
            p_holm=p_holm[(pair, axis)],
            p_equivalence_raw=p_equivalence_raw[(pair, axis)],
            p_equivalence_holm=p_equivalence_holm[(pair, axis)],
            family_size=len(gaps),
            minimum_detectable_family=family_detectable(gaps[(pair, axis)], settings.confidence_level, len(gaps)),
            equivalence_power=power_at_zero_gap(
                gaps[(pair, axis)], settings.equivalence_margin, settings.confidence_level
            ),
        )
        for pair, axis in gaps
    }
    return {pair: AxisPair(x=results[(pair, AxisKey.X)], y=results[(pair, AxisKey.Y)]) for pair in pairs}
