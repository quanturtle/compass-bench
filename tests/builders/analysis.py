"""Trial records with a known outcome, and question scores, for scoring and analysis."""

from collections.abc import Sequence
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, Polarity
from compass_bench.domain.design.conditions import BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING, Condition
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.ids import ModelId, QuestionId, TrialKey
from compass_bench.domain.inference import AxisPosition, Bounded, EstimateKind, PairAxis
from compass_bench.domain.instrument.scale import CanonicalRating, DisplayedRating
from compass_bench.domain.outcome import Pending, Replied, TrialOutcome, TrialOutcomeKind, TrialRecord
from compass_bench.domain.reading.reading import DeclineRead, RatingRead, ReadingKind, RuleId, Span
from compass_bench.domain.scoring import QuestionScore
from tests.builders.design import build_condition

BASELINE_CONDITION: Final = build_condition(BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING)


def record_of(
    model: str,
    question: str,
    polarity: Polarity,
    outcome: TrialOutcome,
    condition: Condition = BASELINE_CONDITION,
    repetition: int = 0,
) -> TrialRecord:
    """A trial of the phrasing toward `polarity` under `condition`, with `outcome`; its key names both."""
    trial = Trial(
        key=TrialKey(f"{model}/{question}/{polarity}/{condition.id}/{repetition}"),
        model=ModelId(model),
        question=QuestionId(question),
        polarity=polarity,
        condition=condition.id,
        repetition=repetition,
        position=0,
    )
    return TrialRecord(trial=trial, outcome=outcome)


def rated_record(
    model: str,
    question: str,
    polarity: Polarity,
    rating: int,
    condition: Condition = BASELINE_CONDITION,
    repetition: int = 0,
) -> TrialRecord:
    """An answered trial whose reply read as canonical `rating`; the displayed form is kept equal as evidence."""
    reading = RatingRead(
        kind=ReadingKind.RATING,
        canonical=CanonicalRating(rating),
        displayed=DisplayedRating(rating),
        span=Span(start=0, end=1),
        rule=RuleId("bare_integer"),
        hedge=None,
    )
    outcome = Replied(kind=TrialOutcomeKind.REPLIED, reading=reading, host=None, served_model=None, fingerprint=None)
    return record_of(model, question, polarity, outcome, condition, repetition)


def pending_record(model: str, question: str, polarity: Polarity) -> TrialRecord:
    return record_of(model, question, polarity, Pending(kind=TrialOutcomeKind.PENDING, attempts=0))


def declined_record(
    model: str, question: str, polarity: Polarity, condition: Condition = BASELINE_CONDITION
) -> TrialRecord:
    """A replied trial whose reply read as a decline."""
    reading = DeclineRead(kind=ReadingKind.DECLINE, evidence=Span(start=0, end=1), rule=RuleId("decline_phrase"))
    outcome = Replied(kind=TrialOutcomeKind.REPLIED, reading=reading, host=None, served_model=None, fingerprint=None)
    return record_of(model, question, polarity, outcome, condition)


def bounded(low: float, high: float, questions: int) -> Bounded:
    """An interval at 0.975 with its point at the middle; its minimum detectable mean is set to the interval's width."""
    return Bounded(
        kind=EstimateKind.BOUNDED,
        point=(low + high) / 2,
        low=low,
        high=high,
        level=0.975,
        questions=questions,
        minimum_detectable=high - low,
    )


def position(low: float, high: float, questions: int, coverage: float) -> AxisPosition:
    return AxisPosition(estimate=bounded(low, high, questions), coverage=coverage)


def pair_axis(
    low: float, high: float, questions: int, p_holm: float, p_equivalence: float = 1.0, power: float | None = 0.5
) -> PairAxis:
    """A gap from `low` to `high` with its Holm-adjusted p and no d_z, correlation, or opposed count.

    Each raw p is set to its adjusted value; the family holds this gap alone, so its first step is its own test."""
    return PairAxis(
        gap=bounded(low, high, questions),
        d_z=None,
        correlation=None,
        opposed_questions=None,
        p_raw=p_holm,
        p_holm=p_holm,
        p_equivalence_raw=p_equivalence,
        p_equivalence_holm=p_equivalence,
        family_size=1,
        minimum_detectable_family=high - low,
        equivalence_power=power,
    )


def scores_on(axis: AxisKey, values: Sequence[float]) -> tuple[QuestionScore, ...]:
    """One score per value, on questions `<axis>-00`, `<axis>-01`, and so on."""
    return tuple(
        QuestionScore(question=QuestionId(f"{axis}-{index:02d}"), axis=axis, score=value)
        for index, value in enumerate(values)
    )
