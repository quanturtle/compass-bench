"""Unanswered trials: what they take from a position, and the bounds they leave on it.

A decline, an unreadable reply, a lost request, and a pending trial are all unanswered. The position leaves them
out, which assumes the answers they would have drawn look like the answers given. The bound makes no such
assumption: it fills every unanswered trial at each end of the score range, so the position lies inside it under
any answers to them (Horowitz & Manski, 2000). Nothing here gates a claim.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity, PolarityPair
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.inference import Bounded, estimate
from compass_bench.domain.instrument.questionnaire import Questionnaire, questions_on
from compass_bench.domain.outcome import Replied, TrialRecord
from compass_bench.domain.reading.reading import DeclineRead
from compass_bench.domain.scoring import PhrasingKey, QuestionScore, answered_rating, question_scores
from compass_bench.domain.value import Value

# the ends of the score range an unanswered trial is filled at
LOW_FILL: Final = -1.0
HIGH_FILL: Final = 1.0
# the fills tried for the flip value, from LOW_FILL to HIGH_FILL
FILL_STEPS: Final = 40


class DroppedQuestion(Value):
    """A question left unscored because one of its statements drew no answer; `unanswered` counts its trials."""

    question: QuestionId
    unanswered: int


class Bound(Value):
    """The mean with every unanswered trial filled at either end of the score range.

    The mean lies in [low, high] under any answers to the `filled` trials; with none filled both equal it.
    A question an unanswered statement dropped is scored inside the bound."""

    low: float
    high: float
    filled: int


class AxisUnanswered(Value):
    """One model's unanswered trials on one axis: how many, how many declined toward each pole, the questions
    they drop from the position, the bound they leave on it, and the fill that would flip its side of 0.

    `flip` is the fill at which the interval stops clearing 0 on the side it clears with the answers given: for an
    interval above 0, the highest tried fill at which it no longer lies above 0; for one below 0, the lowest at
    which it no longer lies below. None when the interval contains 0 as it stands, when no tried fill moves it
    across, or when nothing is unanswered. `bound` is None when no question on the axis can be scored."""

    trials: int
    declined: PolarityPair[int]
    dropped: tuple[DroppedQuestion, ...]
    bound: Bound | None
    flip: float | None


def is_unanswered(record: TrialRecord) -> bool:
    return answered_rating(record.outcome) is None


def is_declined(record: TrialRecord) -> bool:
    match record.outcome:
        case Replied(reading=DeclineRead()):
            return True
        case _:
            return False


def axis_questions(axis: AxisKey, questionnaire: Questionnaire) -> set[QuestionId]:
    return {question.id for question in questions_on(questionnaire, axis)}


def own_unanswered(
    model: ModelId, axis: AxisKey, records: Sequence[TrialRecord], questionnaire: Questionnaire
) -> tuple[TrialRecord, ...]:
    """The model's unanswered trials on the axis."""
    on_axis = axis_questions(axis, questionnaire)
    return tuple(
        record
        for record in records
        if record.trial.model == model and record.trial.question in on_axis and is_unanswered(record)
    )


def filled_values(
    values: Mapping[PhrasingKey, Sequence[float]], unanswered: Sequence[TrialRecord], fill: float
) -> dict[PhrasingKey, list[float]]:
    """The answer values with `fill` appended once per unanswered trial, under that trial's phrasing."""
    filled = {key: list(phrasing) for key, phrasing in values.items()}
    for record in unanswered:
        trial = record.trial
        filled.setdefault((trial.model, trial.question, trial.polarity), []).append(fill)
    return filled


def filled_scores(
    model: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    unanswered: Sequence[TrialRecord],
    questionnaire: Questionnaire,
    fill: float,
) -> dict[QuestionId, float]:
    """The model's question scores on `axis` with `unanswered` filled at `fill`, by question."""
    scores = question_scores(filled_values(values, unanswered, fill), questionnaire, (model,))[model]
    return {score.question: score.score for score in scores if score.axis is axis}


def position_bound(
    model: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    unanswered: Sequence[TrialRecord],
    questionnaire: Questionnaire,
) -> Bound | None:
    """`unanswered` are the model's own on the axis; None when no question can be scored even after filling."""
    low = filled_scores(model, axis, values, unanswered, questionnaire, LOW_FILL)
    high = filled_scores(model, axis, values, unanswered, questionnaire, HIGH_FILL)
    if not low:
        return None
    return Bound(low=fmean(low.values()), high=fmean(high.values()), filled=len(unanswered))


def fills() -> tuple[float, ...]:
    """FILL_STEPS + 1 fills from LOW_FILL to HIGH_FILL, evenly spaced."""
    step = (HIGH_FILL - LOW_FILL) / FILL_STEPS
    return tuple(LOW_FILL + index * step for index in range(FILL_STEPS + 1))


def clears_positive(scores: Mapping[QuestionId, float], level: float) -> bool:
    bounded = estimate(list(scores.values()), level)
    return isinstance(bounded, Bounded) and bounded.low > 0


def clears_negative(scores: Mapping[QuestionId, float], level: float) -> bool:
    bounded = estimate(list(scores.values()), level)
    return isinstance(bounded, Bounded) and bounded.high < 0


def flip_fill(
    model: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    unanswered: Sequence[TrialRecord],
    questionnaire: Questionnaire,
    level: float,
) -> float | None:
    """AxisUnanswered.flip: `unanswered` are the model's own on the axis, `level` the position interval's."""
    if not unanswered:
        return None
    given = filled_scores(model, axis, values, (), questionnaire, LOW_FILL)
    if clears_positive(given, level):
        failing = [
            fill
            for fill in fills()
            if not clears_positive(filled_scores(model, axis, values, unanswered, questionnaire, fill), level)
        ]
        return max(failing) if failing else None
    if clears_negative(given, level):
        failing = [
            fill
            for fill in fills()
            if not clears_negative(filled_scores(model, axis, values, unanswered, questionnaire, fill), level)
        ]
        return min(failing) if failing else None
    return None


def axis_unanswered(
    model: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    records: Sequence[TrialRecord],
    scores: Sequence[QuestionScore],
    questionnaire: Questionnaire,
    level: float,
) -> AxisUnanswered:
    """`values` are the pooled answer values and `records` every model's; `scores` are the model's own."""
    unanswered = own_unanswered(model, axis, records, questionnaire)
    declined = Counter(record.trial.polarity for record in unanswered if is_declined(record))
    per_question = Counter(record.trial.question for record in unanswered)
    scored = {score.question for score in scores if score.axis is axis}
    asked = {record.trial.question for record in records if record.trial.model == model}
    return AxisUnanswered(
        trials=len(unanswered),
        declined=PolarityPair(negative=declined[Polarity.NEGATIVE], positive=declined[Polarity.POSITIVE]),
        dropped=tuple(
            DroppedQuestion(question=question.id, unanswered=per_question[question.id])
            for question in questions_on(questionnaire, axis)
            if question.id in asked and question.id not in scored
        ),
        bound=position_bound(model, axis, values, unanswered, questionnaire),
        flip=flip_fill(model, axis, values, unanswered, questionnaire, level),
    )


def model_unanswered(
    model: ModelId,
    values: Mapping[PhrasingKey, Sequence[float]],
    records: Sequence[TrialRecord],
    scores: Sequence[QuestionScore],
    questionnaire: Questionnaire,
    level: float,
) -> AxisPair[AxisUnanswered]:
    return AxisPair(
        x=axis_unanswered(model, AxisKey.X, values, records, scores, questionnaire, level),
        y=axis_unanswered(model, AxisKey.Y, values, records, scores, questionnaire, level),
    )


def gap_bound(
    first: ModelId,
    second: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    records: Sequence[TrialRecord],
    questionnaire: Questionnaire,
) -> Bound | None:
    """The second model minus the first over the questions both score after filling: the low end fills the second
    low and the first high, the high end the reverse. None without a shared question."""
    first_unanswered = own_unanswered(first, axis, records, questionnaire)
    second_unanswered = own_unanswered(second, axis, records, questionnaire)
    first_low = filled_scores(first, axis, values, first_unanswered, questionnaire, LOW_FILL)
    first_high = filled_scores(first, axis, values, first_unanswered, questionnaire, HIGH_FILL)
    second_low = filled_scores(second, axis, values, second_unanswered, questionnaire, LOW_FILL)
    second_high = filled_scores(second, axis, values, second_unanswered, questionnaire, HIGH_FILL)
    shared = [question for question in first_low if question in second_low]
    if not shared:
        return None
    return Bound(
        low=fmean(second_low[question] - first_high[question] for question in shared),
        high=fmean(second_high[question] - first_low[question] for question in shared),
        filled=len(first_unanswered) + len(second_unanswered),
    )


def pair_bounds(
    first: ModelId,
    second: ModelId,
    values: Mapping[PhrasingKey, Sequence[float]],
    records: Sequence[TrialRecord],
    questionnaire: Questionnaire,
) -> AxisPair[Bound | None]:
    return AxisPair(
        x=gap_bound(first, second, AxisKey.X, values, records, questionnaire),
        y=gap_bound(first, second, AxisKey.Y, values, records, questionnaire),
    )
