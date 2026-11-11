"""The only place a claim is decided. Every gate runs, and a withheld claim carries every failing reason."""

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity
from compass_bench.domain.design.experiment import AnalysisSettings, significance_level
from compass_bench.domain.ids import ModelId
from compass_bench.domain.inference import AxisPosition, Bounded, Estimate, PairAxis
from compass_bench.domain.value import Value

# the fewest questions a position or a pair gap may rest on; with AnalysisSettings.coverage_floor,
# the one missing-data floor for quadrant and ordering claims alike
MIN_QUESTIONS: Final = 10


class Ordering(StrEnum):
    FIRST_HIGHER = "first_higher"
    SECOND_HIGHER = "second_higher"


class Equivalence(Value):
    """Two models' gap on an axis lies within `margin`, in score units."""

    margin: float


class ReasonKind(StrEnum):
    CROSSES_MIDPOINT = "crosses_midpoint"
    TOO_FEW_QUESTIONS = "too_few_questions"
    COVERAGE_BELOW_FLOOR = "coverage_below_floor"
    NOT_SIGNIFICANT = "not_significant"
    NOT_EQUIVALENT = "not_equivalent"
    RUN_INCOMPLETE = "run_incomplete"


class CrossesMidpoint(Value):
    """The axis interval contains 0, so it clears neither pole."""

    kind: Literal[ReasonKind.CROSSES_MIDPOINT]
    axis: AxisKey


class TooFewQuestions(Value):
    """The position or gap rests on fewer questions than the minimum."""

    kind: Literal[ReasonKind.TOO_FEW_QUESTIONS]
    axis: AxisKey
    observed: int
    minimum: int


class CoverageBelowFloor(Value):
    """Too small a share of the model's trials on the axis were answered."""

    kind: Literal[ReasonKind.COVERAGE_BELOW_FLOOR]
    model: ModelId
    axis: AxisKey
    observed: float
    floor: float


class NotSignificant(Value):
    """The gap's Holm-adjusted p-value is at least alpha."""

    kind: Literal[ReasonKind.NOT_SIGNIFICANT]
    axis: AxisKey
    p_holm: float
    alpha: float


class NotEquivalent(Value):
    """The two one-sided tests' Holm-adjusted p-value is at least alpha, so the gap is not shown to be small.

    `power_at_zero_gap` is the unadjusted tests' power to show a true gap of 0 within the margin, given the
    observed spread, None when the gap is not estimable; a low value says the questions could not have shown
    equivalence whatever the gap."""

    kind: Literal[ReasonKind.NOT_EQUIVALENT]
    axis: AxisKey
    p_holm: float
    alpha: float
    margin: float
    power_at_zero_gap: float | None


class RunIncomplete(Value):
    """Trials are still pending, so the result can change when the run resumes."""

    kind: Literal[ReasonKind.RUN_INCOMPLETE]
    pending: int


type Reason = Annotated[
    CrossesMidpoint | TooFewQuestions | CoverageBelowFloor | NotSignificant | NotEquivalent | RunIncomplete,
    Field(discriminator="kind"),
]


class ClaimKind(StrEnum):
    ASSERTED = "asserted"
    WITHHELD = "withheld"


class Asserted[T](Value):
    kind: Literal[ClaimKind.ASSERTED]
    value: T


class Withheld(Value):
    """Never empty: a withheld claim always says why."""

    kind: Literal[ClaimKind.WITHHELD]
    reasons: Annotated[tuple[Reason, ...], Field(min_length=1)]


type Claim[T] = Annotated[Asserted[T] | Withheld, Field(discriminator="kind")]
type QuadrantClaim = Claim[AxisPair[Polarity]]
type OrderingClaim = Claim[Ordering]
type EquivalenceClaim = Claim[Equivalence]


class UnclaimableEstimate(Exception):
    """Every gate passed, yet the estimate names no pole or direction: a gate is missing."""


def question_reasons(estimate: Estimate, axis: AxisKey) -> tuple[Reason, ...]:
    """TooFewQuestions below MIN_QUESTIONS, whether or not the estimate has an interval."""
    if estimate.questions >= MIN_QUESTIONS:
        return ()
    return (
        TooFewQuestions(
            kind=ReasonKind.TOO_FEW_QUESTIONS, axis=axis, observed=estimate.questions, minimum=MIN_QUESTIONS
        ),
    )


def coverage_reasons(model: ModelId, position: AxisPosition, axis: AxisKey, floor: float) -> tuple[Reason, ...]:
    if position.coverage >= floor:
        return ()
    return (
        CoverageBelowFloor(
            kind=ReasonKind.COVERAGE_BELOW_FLOOR, model=model, axis=axis, observed=position.coverage, floor=floor
        ),
    )


def midline_reasons(estimate: Estimate, axis: AxisKey) -> tuple[Reason, ...]:
    """CrossesMidpoint when a bounded interval contains 0; an estimate without one is gated by its question count."""
    match estimate:
        case Bounded(low=low, high=high) if low <= 0 <= high:
            return (CrossesMidpoint(kind=ReasonKind.CROSSES_MIDPOINT, axis=axis),)
        case _:
            return ()


def significance_reasons(pair: PairAxis, axis: AxisKey, alpha: float) -> tuple[Reason, ...]:
    if pair.p_holm < alpha:
        return ()
    return (NotSignificant(kind=ReasonKind.NOT_SIGNIFICANT, axis=axis, p_holm=pair.p_holm, alpha=alpha),)


def equivalence_reasons(pair: PairAxis, axis: AxisKey, alpha: float, margin: float) -> tuple[Reason, ...]:
    if pair.p_equivalence_holm < alpha:
        return ()
    return (
        NotEquivalent(
            kind=ReasonKind.NOT_EQUIVALENT,
            axis=axis,
            p_holm=pair.p_equivalence_holm,
            alpha=alpha,
            margin=margin,
            power_at_zero_gap=pair.equivalence_power,
        ),
    )


def completeness_reasons(pending: int) -> tuple[Reason, ...]:
    if pending == 0:
        return ()
    return (RunIncomplete(kind=ReasonKind.RUN_INCOMPLETE, pending=pending),)


def position_reasons(
    model: ModelId, position: AxisPosition, axis: AxisKey, settings: AnalysisSettings
) -> tuple[Reason, ...]:
    """Every gate on one axis of a quadrant: the question count, the coverage, and the midline."""
    return (
        question_reasons(position.estimate, axis)
        + coverage_reasons(model, position, axis, settings.coverage_floor)
        + midline_reasons(position.estimate, axis)
    )


def cleared_pole(position: AxisPosition) -> Polarity:
    """The pole on the side of 0 the interval clears."""
    match position.estimate:
        case Bounded(low=low) if low > 0:
            return Polarity.POSITIVE
        case Bounded(high=high) if high < 0:
            return Polarity.NEGATIVE
        case _:
            raise UnclaimableEstimate(f"the gates passed an estimate that clears no pole: {position.estimate}")


def quadrant_claim(
    model: ModelId, axes: AxisPair[AxisPosition], settings: AnalysisSettings, pending: int
) -> QuadrantClaim:
    """The pole comes from the side of 0 each interval clears, never from the point estimate.

    `pending` counts the model's own pending trials, since only they can move its positions."""
    reasons = (
        position_reasons(model, axes.x, AxisKey.X, settings)
        + position_reasons(model, axes.y, AxisKey.Y, settings)
        + completeness_reasons(pending)
    )
    if reasons:
        return Withheld(kind=ClaimKind.WITHHELD, reasons=reasons)
    return Asserted[AxisPair[Polarity]](kind=ClaimKind.ASSERTED, value=axes.map(cleared_pole))


def ordering_claim(pair: PairAxis, reasons: tuple[Reason, ...]) -> OrderingClaim:
    """Withheld with every failing reason, else the order the gap's sign gives."""
    if reasons:
        return Withheld(kind=ClaimKind.WITHHELD, reasons=reasons)
    match pair.gap:
        case Bounded(point=point) if point > 0:
            return Asserted[Ordering](kind=ClaimKind.ASSERTED, value=Ordering.SECOND_HIGHER)
        case Bounded(point=point) if point < 0:
            return Asserted[Ordering](kind=ClaimKind.ASSERTED, value=Ordering.FIRST_HIGHER)
        case _:
            raise UnclaimableEstimate(f"the gates passed a gap with no direction: {pair.gap}")


def pair_floor_reasons(
    pair: PairAxis,
    axis: AxisKey,
    first: ModelId,
    first_position: AxisPosition,
    second: ModelId,
    second_position: AxisPosition,
    floor: float,
) -> tuple[Reason, ...]:
    """The gates an ordering and an equivalence share: the shared question count and both models' coverage."""
    return (
        question_reasons(pair.gap, axis)
        + coverage_reasons(first, first_position, axis, floor)
        + coverage_reasons(second, second_position, axis, floor)
    )


def ordering_claims(
    pair: AxisPair[PairAxis],
    first: ModelId,
    first_axes: AxisPair[AxisPosition],
    second: ModelId,
    second_axes: AxisPair[AxisPosition],
    settings: AnalysisSettings,
    pending: int,
) -> AxisPair[OrderingClaim]:
    """One claim per axis, gated on both models' coverage, the shared question count, and the Holm-adjusted p.

    The order comes from the gap's sign; a missing claim never means the models are equal. `pending` counts the
    run's pending trials, since Holm ties every pair's p to every other pair's."""
    alpha = significance_level(settings)
    floor = settings.coverage_floor
    claims = {
        axis: ordering_claim(
            pair.get(axis),
            pair_floor_reasons(pair.get(axis), axis, first, first_axes.get(axis), second, second_axes.get(axis), floor)
            + significance_reasons(pair.get(axis), axis, alpha)
            + completeness_reasons(pending),
        )
        for axis in AxisKey
    }
    return AxisPair[OrderingClaim](x=claims[AxisKey.X], y=claims[AxisKey.Y])


def equivalence_claim(reasons: tuple[Reason, ...], margin: float) -> EquivalenceClaim:
    """Withheld with every failing reason, else equivalence within the margin."""
    if reasons:
        return Withheld(kind=ClaimKind.WITHHELD, reasons=reasons)
    return Asserted[Equivalence](kind=ClaimKind.ASSERTED, value=Equivalence(margin=margin))


def equivalence_claims(
    pair: AxisPair[PairAxis],
    first: ModelId,
    first_axes: AxisPair[AxisPosition],
    second: ModelId,
    second_axes: AxisPair[AxisPosition],
    settings: AnalysisSettings,
    pending: int,
) -> AxisPair[EquivalenceClaim]:
    """One claim per axis under the ordering gates, with the equivalence tests' Holm-adjusted p in place of the gap's.

    An asserted equivalence says the gap lies within `equivalence_margin`; an ordering and an equivalence can both
    hold when a gap is real but smaller than the margin."""
    alpha = significance_level(settings)
    floor = settings.coverage_floor
    claims = {
        axis: equivalence_claim(
            pair_floor_reasons(pair.get(axis), axis, first, first_axes.get(axis), second, second_axes.get(axis), floor)
            + equivalence_reasons(pair.get(axis), axis, alpha, settings.equivalence_margin)
            + completeness_reasons(pending),
            settings.equivalence_margin,
        )
        for axis in AxisKey
    }
    return AxisPair[EquivalenceClaim](x=claims[AxisKey.X], y=claims[AxisKey.Y])


class PairOutcome(StrEnum):
    """Lakens's (2017) four readings of an ordering test beside an equivalence test on one gap."""

    DIFFERENT_NOT_EQUIVALENT = "different_not_equivalent"
    DIFFERENT_AND_EQUIVALENT = "different_and_equivalent"
    EQUIVALENT_NOT_DIFFERENT = "equivalent_not_different"
    UNDETERMINED = "undetermined"


def pair_outcome(ordering: OrderingClaim, equivalence: EquivalenceClaim) -> PairOutcome:
    """Different when the ordering is asserted, equivalent when the equivalence is; neither is undetermined."""
    match (ordering, equivalence):
        case (Asserted(), Asserted()):
            return PairOutcome.DIFFERENT_AND_EQUIVALENT
        case (Asserted(), Withheld()):
            return PairOutcome.DIFFERENT_NOT_EQUIVALENT
        case (Withheld(), Asserted()):
            return PairOutcome.EQUIVALENT_NOT_DIFFERENT
        case _:
            return PairOutcome.UNDETERMINED


def pair_outcomes(
    orderings: AxisPair[OrderingClaim], equivalences: AxisPair[EquivalenceClaim]
) -> AxisPair[PairOutcome]:
    return AxisPair(
        x=pair_outcome(orderings.x, equivalences.x),
        y=pair_outcome(orderings.y, equivalences.y),
    )
