"""Question scores: each answer on [-1, 1] toward the axis's positive pole, averaged per phrasing, then per question."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from statistics import fmean

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.instrument.questionnaire import Question, Questionnaire, facets_on, question_index
from compass_bench.domain.instrument.scale import CanonicalRating, Scale, normalize
from compass_bench.domain.outcome import Replied, TrialOutcome, TrialRecord
from compass_bench.domain.reading.reading import RatingRead
from compass_bench.domain.value import Value

# one model's answers to one phrasing of one question
type PhrasingKey = tuple[ModelId, QuestionId, Polarity]


class QuestionScore(Value):
    """A model's score on one question: the mean of its two phrasing means, each over every condition and repetition.

    Scored only when both phrasings have an answer, so leaning to a list position, a number, or agreeing cancels."""

    question: QuestionId
    axis: AxisKey
    score: float


class FacetScore(Value):
    """A model's mean question score over one facet of an axis; None when none of the facet's questions is scored.

    Facets hold few questions, so no interval is given and nothing is claimed from them."""

    axis: AxisKey
    facet: str
    questions: int
    mean: float | None


def answer_value(rating: CanonicalRating, polarity: Polarity, scale: Scale) -> float:
    """normalize(scale, rating) times the phrasing's polarity, so +1 always points to the axis's positive pole."""
    return normalize(scale, rating) * polarity


def answered_rating(outcome: TrialOutcome) -> CanonicalRating | None:
    """The canonical rating of an answered trial; a decline, a format failure, a loss, or a pending trial has none."""
    match outcome:
        case Replied(reading=RatingRead(canonical=rating)):
            return rating
        case _:
            return None


def phrasing_values(records: Sequence[TrialRecord], scale: Scale) -> dict[PhrasingKey, list[float]]:
    """Each answered trial's answer value, grouped by model, question, and phrasing."""
    values: defaultdict[PhrasingKey, list[float]] = defaultdict(list)
    for record in records:
        rating = answered_rating(record.outcome)
        if rating is not None:
            trial = record.trial
            values[(trial.model, trial.question, trial.polarity)].append(answer_value(rating, trial.polarity, scale))
    return values


def pooled_values(groups: Iterable[Mapping[PhrasingKey, Sequence[float]]]) -> dict[PhrasingKey, list[float]]:
    """Each phrasing's answer values from every group, so a model's runs pool into one set of answers."""
    pooled: defaultdict[PhrasingKey, list[float]] = defaultdict(list)
    for values in groups:
        for key, phrasing in values.items():
            pooled[key].extend(phrasing)
    return dict(pooled)


def question_score(
    model: ModelId, question: Question, values: Mapping[PhrasingKey, Sequence[float]]
) -> QuestionScore | None:
    """The mean of the two phrasing means, or None when a phrasing has no answer."""
    phrasings = [values.get((model, question.id, polarity), ()) for polarity in Polarity]
    if not all(phrasings):
        return None
    return QuestionScore(
        question=question.id, axis=question.axis, score=fmean(fmean(phrasing) for phrasing in phrasings)
    )


def question_scores(
    values: Mapping[PhrasingKey, Sequence[float]], questionnaire: Questionnaire, models: Sequence[ModelId]
) -> Mapping[ModelId, tuple[QuestionScore, ...]]:
    """Each model's scored questions in questionnaire order.

    `values` come from phrasing_values, each on the scale its trial was asked on, so several runs' values can pool."""
    return {
        model: tuple(
            score
            for question in questionnaire.questions
            if (score := question_score(model, question, values)) is not None
        )
        for model in models
    }


def facet_scores(scores: Sequence[QuestionScore], questionnaire: Questionnaire) -> tuple[FacetScore, ...]:
    """One model's mean score per facet, in questionnaire order: every facet of both axes, scored or not."""
    facets = question_index(questionnaire)
    by_facet: defaultdict[tuple[AxisKey, str], list[float]] = defaultdict(list)
    for score in scores:
        by_facet[(score.axis, facets[score.question].facet)].append(score.score)
    return tuple(
        FacetScore(
            axis=axis,
            facet=facet,
            questions=len(by_facet[(axis, facet)]),
            mean=fmean(by_facet[(axis, facet)]) if by_facet[(axis, facet)] else None,
        )
        for axis in AxisKey
        for facet in facets_on(questionnaire, axis)
    )


def axis_coverage(records: Sequence[TrialRecord], questionnaire: Questionnaire) -> Mapping[ModelId, AxisPair[float]]:
    """Each model's answered trials on an axis over all its trials there, pending ones included."""
    axes = {question.id: question.axis for question in questionnaire.questions}
    trials = Counter((record.trial.model, axes[record.trial.question]) for record in records)
    answered = Counter(
        (record.trial.model, axes[record.trial.question])
        for record in records
        if answered_rating(record.outcome) is not None
    )
    return {
        model: AxisPair(
            x=answered[(model, AxisKey.X)] / trials[(model, AxisKey.X)],
            y=answered[(model, AxisKey.Y)] / trials[(model, AxisKey.Y)],
        )
        for model in sorted({model for model, _ in trials})
    }
