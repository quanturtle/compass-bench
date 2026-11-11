import pytest

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity
from compass_bench.domain.claims import (
    MIN_QUESTIONS,
    Asserted,
    ClaimKind,
    CoverageBelowFloor,
    CrossesMidpoint,
    Equivalence,
    EquivalenceClaim,
    NotEquivalent,
    NotSignificant,
    Ordering,
    OrderingClaim,
    PairOutcome,
    Reason,
    ReasonKind,
    RunIncomplete,
    TooFewQuestions,
    UnclaimableEstimate,
    Withheld,
    cleared_pole,
    equivalence_claims,
    ordering_claim,
    ordering_claims,
    pair_outcome,
    quadrant_claim,
)
from compass_bench.domain.design.experiment import AnalysisSettings, significance_level
from compass_bench.domain.ids import ModelId
from tests.builders.analysis import pair_axis, position

SETTINGS = AnalysisSettings(confidence_level=0.95, coverage_floor=0.8, equivalence_margin=0.1)
MODEL, OTHER = ModelId("model"), ModelId("other")
CLEAR = position(0.1, 0.5, questions=MIN_QUESTIONS, coverage=1.0)


def withheld_reasons(claim: OrderingClaim | EquivalenceClaim) -> tuple[Reason, ...]:
    assert isinstance(claim, Withheld)
    return claim.reasons


def test_an_interval_that_crosses_the_midline_is_never_asserted() -> None:
    edges = [step / 10 for step in range(6)]
    for low in edges:
        for high in edges:
            crossing = position(-low, high, questions=MIN_QUESTIONS, coverage=1.0)
            for axes in (AxisPair(x=crossing, y=CLEAR), AxisPair(x=CLEAR, y=crossing)):
                assert isinstance(quadrant_claim(MODEL, axes, SETTINGS, pending=0), Withheld)


def test_the_pole_is_the_side_each_interval_clears() -> None:
    axes = AxisPair(x=CLEAR, y=position(-0.5, -0.01, questions=MIN_QUESTIONS, coverage=1.0))

    claim = quadrant_claim(MODEL, axes, SETTINGS, pending=0)

    assert claim == Asserted(kind=ClaimKind.ASSERTED, value=AxisPair(x=Polarity.POSITIVE, y=Polarity.NEGATIVE))


def test_a_withheld_quadrant_carries_every_failing_reason() -> None:
    axes = AxisPair(x=position(-0.1, 0.3, questions=4, coverage=0.5), y=CLEAR)

    claim = quadrant_claim(MODEL, axes, SETTINGS, pending=3)

    assert claim == Withheld(
        kind=ClaimKind.WITHHELD,
        reasons=(
            TooFewQuestions(kind=ReasonKind.TOO_FEW_QUESTIONS, axis=AxisKey.X, observed=4, minimum=MIN_QUESTIONS),
            CoverageBelowFloor(
                kind=ReasonKind.COVERAGE_BELOW_FLOOR, model=MODEL, axis=AxisKey.X, observed=0.5, floor=0.8
            ),
            CrossesMidpoint(kind=ReasonKind.CROSSES_MIDPOINT, axis=AxisKey.X),
            RunIncomplete(kind=ReasonKind.RUN_INCOMPLETE, pending=3),
        ),
    )


def test_an_ordering_follows_the_gap_sign_once_significant_and_names_the_model_below_the_coverage_floor() -> None:
    pair = AxisPair(
        x=pair_axis(-0.6, -0.2, questions=MIN_QUESTIONS, p_holm=0.01),
        y=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.01),
    )
    sparse = AxisPair(x=CLEAR, y=position(0.1, 0.5, questions=MIN_QUESTIONS, coverage=0.5))

    claims = ordering_claims(pair, MODEL, AxisPair(x=CLEAR, y=CLEAR), OTHER, sparse, SETTINGS, pending=0)

    assert claims.x == Asserted(kind=ClaimKind.ASSERTED, value=Ordering.FIRST_HIGHER)
    assert claims.y == Withheld(
        kind=ClaimKind.WITHHELD,
        reasons=(
            CoverageBelowFloor(
                kind=ReasonKind.COVERAGE_BELOW_FLOOR, model=OTHER, axis=AxisKey.Y, observed=0.5, floor=0.8
            ),
        ),
    )


def test_coverage_at_the_floor_passes_and_a_p_at_alpha_does_not() -> None:
    even = AnalysisSettings(confidence_level=0.5, coverage_floor=0.8, equivalence_margin=0.1)
    at_floor = position(0.1, 0.5, questions=MIN_QUESTIONS, coverage=0.8)
    pair = AxisPair(
        x=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.5),
        y=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.25),
    )
    axes = AxisPair(x=at_floor, y=at_floor)

    claims = ordering_claims(pair, MODEL, axes, OTHER, axes, even, pending=0)

    assert [reason.kind for reason in withheld_reasons(claims.x)] == [ReasonKind.NOT_SIGNIFICANT]
    assert claims.y == Asserted(kind=ClaimKind.ASSERTED, value=Ordering.SECOND_HIGHER)


def test_an_ordering_on_too_few_shared_questions_is_withheld() -> None:
    pair = AxisPair(
        x=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS - 1, p_holm=0.01),
        y=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.01),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    claims = ordering_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=0)

    assert withheld_reasons(claims.x) == (
        TooFewQuestions(
            kind=ReasonKind.TOO_FEW_QUESTIONS, axis=AxisKey.X, observed=MIN_QUESTIONS - 1, minimum=MIN_QUESTIONS
        ),
    )


@pytest.mark.parametrize("low, high", [(0.0, 0.5), (-0.5, 0.0), (-0.5, 0.5)])
def test_an_interval_that_touches_or_crosses_0_names_no_pole_even_past_the_gates(low: float, high: float) -> None:
    with pytest.raises(UnclaimableEstimate, match="clears no pole"):
        cleared_pole(position(low, high, questions=MIN_QUESTIONS, coverage=1.0))


def test_a_zero_gap_names_no_direction_even_past_the_gates() -> None:
    with pytest.raises(UnclaimableEstimate, match="no direction"):
        ordering_claim(pair_axis(-0.5, 0.5, questions=MIN_QUESTIONS, p_holm=0.01), reasons=())


def test_an_equivalence_holds_when_its_holm_p_is_below_alpha_under_the_ordering_gates() -> None:
    pair = AxisPair(
        x=pair_axis(-0.05, 0.05, questions=MIN_QUESTIONS, p_holm=0.9, p_equivalence=0.01),
        y=pair_axis(-0.05, 0.05, questions=MIN_QUESTIONS - 1, p_holm=0.9, p_equivalence=0.2),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    claims = equivalence_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=0)

    assert claims.x == Asserted(kind=ClaimKind.ASSERTED, value=Equivalence(margin=0.1))
    assert withheld_reasons(claims.y) == (
        TooFewQuestions(
            kind=ReasonKind.TOO_FEW_QUESTIONS, axis=AxisKey.Y, observed=MIN_QUESTIONS - 1, minimum=MIN_QUESTIONS
        ),
        NotEquivalent(
            kind=ReasonKind.NOT_EQUIVALENT,
            axis=AxisKey.Y,
            p_holm=0.2,
            alpha=significance_level(SETTINGS),
            margin=SETTINGS.equivalence_margin,
            power_at_zero_gap=0.5,
        ),
    )


def test_a_withheld_equivalence_carries_the_tests_power_at_a_zero_gap() -> None:
    pair = AxisPair(
        x=pair_axis(-0.2, 0.2, questions=MIN_QUESTIONS, p_holm=0.9, p_equivalence=0.6, power=0.12),
        y=pair_axis(-0.05, 0.05, questions=MIN_QUESTIONS, p_holm=0.9, p_equivalence=0.6, power=None),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    claims = equivalence_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=0)

    (x_reason,) = withheld_reasons(claims.x)
    (y_reason,) = withheld_reasons(claims.y)
    assert isinstance(x_reason, NotEquivalent) and isinstance(y_reason, NotEquivalent)
    assert (x_reason.power_at_zero_gap, y_reason.power_at_zero_gap) == (0.12, None)


def test_the_pair_outcome_reads_the_ordering_and_the_equivalence_together() -> None:
    different = Asserted[Ordering](kind=ClaimKind.ASSERTED, value=Ordering.FIRST_HIGHER)
    equivalent = Asserted[Equivalence](kind=ClaimKind.ASSERTED, value=Equivalence(margin=0.1))
    withheld = Withheld(kind=ClaimKind.WITHHELD, reasons=(RunIncomplete(kind=ReasonKind.RUN_INCOMPLETE, pending=1),))

    assert pair_outcome(different, withheld) is PairOutcome.DIFFERENT_NOT_EQUIVALENT
    assert pair_outcome(different, equivalent) is PairOutcome.DIFFERENT_AND_EQUIVALENT
    assert pair_outcome(withheld, equivalent) is PairOutcome.EQUIVALENT_NOT_DIFFERENT
    assert pair_outcome(withheld, withheld) is PairOutcome.UNDETERMINED


def test_an_equivalence_p_at_alpha_is_not_equivalent() -> None:
    even = AnalysisSettings(confidence_level=0.5, coverage_floor=0.8, equivalence_margin=0.1)
    pair = AxisPair(
        x=pair_axis(-0.05, 0.05, questions=MIN_QUESTIONS, p_holm=0.9, p_equivalence=0.5),
        y=pair_axis(-0.05, 0.05, questions=MIN_QUESTIONS, p_holm=0.9, p_equivalence=0.25),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    claims = equivalence_claims(pair, MODEL, both, OTHER, both, even, pending=0)

    assert [reason.kind for reason in withheld_reasons(claims.x)] == [ReasonKind.NOT_EQUIVALENT]
    assert claims.y == Asserted(kind=ClaimKind.ASSERTED, value=Equivalence(margin=0.1))


def test_an_ordering_and_an_equivalence_can_both_hold_for_a_small_real_gap() -> None:
    pair = AxisPair(
        x=pair_axis(0.01, 0.05, questions=MIN_QUESTIONS, p_holm=0.01, p_equivalence=0.01),
        y=pair_axis(0.01, 0.05, questions=MIN_QUESTIONS, p_holm=0.01, p_equivalence=0.01),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    orderings = ordering_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=0)
    equivalences = equivalence_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=3)

    assert orderings.x == Asserted(kind=ClaimKind.ASSERTED, value=Ordering.SECOND_HIGHER)
    assert withheld_reasons(equivalences.x) == (RunIncomplete(kind=ReasonKind.RUN_INCOMPLETE, pending=3),)


def test_a_gap_above_alpha_is_not_significant() -> None:
    pair = AxisPair(
        x=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.06),
        y=pair_axis(0.2, 0.6, questions=MIN_QUESTIONS, p_holm=0.04),
    )
    both = AxisPair(x=CLEAR, y=CLEAR)

    claims = ordering_claims(pair, MODEL, both, OTHER, both, SETTINGS, pending=0)

    assert isinstance(claims.x, Withheld) and len(claims.x.reasons) == 1
    assert isinstance(claims.x.reasons[0], NotSignificant) and claims.x.reasons[0].p_holm == 0.06
    assert claims.y == Asserted(kind=ClaimKind.ASSERTED, value=Ordering.SECOND_HIGHER)
