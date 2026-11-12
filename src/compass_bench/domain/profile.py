"""Response profile per model and axis: how the scale's points are used, how the question scores split around 0,
and how far each statement's answers agree with each other. These numbers gate no claim.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean, stdev
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair
from compass_bench.domain.ids import ModelId
from compass_bench.domain.instrument.questionnaire import Questionnaire, questions_on
from compass_bench.domain.instrument.scale import CanonicalRating, Scale, center, points
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.scoring import FacetScore, PhrasingKey, QuestionScore, answered_rating
from compass_bench.domain.stats.icc import icc_one_way
from compass_bench.domain.value import Value

# a statement whose ratings span this many points or more across its cells counts as widely spread
WIDE_RANGE: Final = 2
# how many question scores the profile names as farthest from the position
FARTHEST_SHOWN: Final = 3
# two models use the scale unequally when one's rating sd is this many times the other's; a convention, since the
# clamped scale pulls the broader model's mean toward 0 less (Liddell & Kruschke, 2018)
SCALE_USE_RATIO: Final = 1.5


class RatingProfile(Value):
    """How a model uses the scale's points on one axis, over its answered trials there.

    `shares` run from the scale's first point to its last; `midpoint_share` is None on a scale without a
    midpoint; `rating_sd` is the sample standard deviation of the ratings, None below two."""

    answered: int
    shares: tuple[float, ...]
    midpoint_share: float | None
    ends_share: float
    rating_sd: float | None


class ScoreSplit(Value):
    """How the question scores split around 0: a position near 0 from scores near 0 and one from scores that
    cancel each other look alike until `mean_absolute` is read beside |position|.

    `opposing_facets` counts facets whose mean sits on the other side of 0 from the position. `facet_balanced` is
    the mean of the facet means, each facet weighing the same; None while any facet of the axis is unscored.
    `farthest` holds the FARTHEST_SHOWN question scores farthest from the position, farthest first and in
    questionnaire order on a tie: the ones that pull it most. It is empty below two scores, where the position has
    no interval."""

    positive: int
    negative: int
    zero: int
    mean_absolute: float | None
    opposing_facets: int
    facet_balanced: float | None
    farthest: tuple[QuestionScore, ...]


class StatementAgreement(Value):
    """How far each statement's answers agree with each other across the layouts and wordings it was asked in.

    Among the `statements` with two or more answers, `one_sided` counts those whose answers all lie on one side
    of the scale's center, `identical` those whose answers are all one rating, and `wide` those whose answers
    span `wide_range` or more rating points, WIDE_RANGE. `icc` is ICC(1) with statements as groups over canonical
    ratings: the share of the rating variance that lies between statements rather than within them; None below
    two statements with answers or without spread."""

    one_sided: int
    identical: int
    wide: int
    wide_range: int
    statements: int
    icc: float | None


class AxisProfile(Value):
    ratings: RatingProfile
    scores: ScoreSplit
    statements: StatementAgreement


class ScaleUse(Value):
    """Two models' rating spreads on one axis, in canonical model order; `differs` when the larger standard deviation
    is at least SCALE_USE_RATIO times the smaller, so their gap is partly one of scale use."""

    sd_first: float | None
    sd_second: float | None
    differs: bool


def axis_ratings(
    model: ModelId, axis: AxisKey, records: Sequence[TrialRecord], questionnaire: Questionnaire
) -> dict[PhrasingKey, list[CanonicalRating]]:
    """The model's answered canonical ratings on the axis, by phrasing."""
    on_axis = {question.id for question in questions_on(questionnaire, axis)}
    ratings: defaultdict[PhrasingKey, list[CanonicalRating]] = defaultdict(list)
    for record in records:
        trial = record.trial
        rating = answered_rating(record.outcome)
        if trial.model == model and trial.question in on_axis and rating is not None:
            ratings[(trial.model, trial.question, trial.polarity)].append(rating)
    return dict(ratings)


def rating_profile(ratings: Sequence[CanonicalRating], scale: Scale) -> RatingProfile:
    counts = Counter(ratings)
    answered = len(ratings)
    shares = tuple(
        counts[CanonicalRating(point)] / answered if answered else 0.0 for point in range(1, points(scale) + 1)
    )
    has_midpoint = points(scale) % 2 == 1
    return RatingProfile(
        answered=answered,
        shares=shares,
        midpoint_share=shares[points(scale) // 2] if has_midpoint else None,
        ends_share=shares[0] + shares[-1] if answered else 0.0,
        rating_sd=stdev(ratings) if answered >= 2 else None,
    )


def farthest_scores(scores: Sequence[QuestionScore], position: float) -> tuple[QuestionScore, ...]:
    """The FARTHEST_SHOWN scores farthest from `position`; the sort is stable, so a tie keeps questionnaire order."""
    if len(scores) < 2:
        return ()
    return tuple(sorted(scores, key=lambda score: abs(score.score - position), reverse=True)[:FARTHEST_SHOWN])


def score_split(scores: Sequence[QuestionScore], facets: Sequence[FacetScore], axis: AxisKey) -> ScoreSplit:
    on_axis_scores = [score for score in scores if score.axis is axis]
    values = [score.score for score in on_axis_scores]
    position = fmean(values) if values else 0.0
    on_axis = [facet.mean for facet in facets if facet.axis is axis]
    means = [mean for mean in on_axis if mean is not None]
    return ScoreSplit(
        positive=sum(value > 0 for value in values),
        negative=sum(value < 0 for value in values),
        zero=sum(value == 0 for value in values),
        mean_absolute=fmean(abs(value) for value in values) if values else None,
        opposing_facets=sum(mean * position < 0 for mean in means),
        facet_balanced=fmean(means) if means and len(means) == len(on_axis) else None,
        farthest=farthest_scores(on_axis_scores, position),
    )


def is_one_sided(ratings: Sequence[CanonicalRating], scale: Scale) -> bool:
    """Every rating lies strictly above the center, or every one strictly below it."""
    return all(rating > center(scale) for rating in ratings) or all(rating < center(scale) for rating in ratings)


def statement_agreement(ratings: Mapping[PhrasingKey, Sequence[CanonicalRating]], scale: Scale) -> StatementAgreement:
    repeated = [statement for statement in ratings.values() if len(statement) >= 2]
    return StatementAgreement(
        one_sided=sum(is_one_sided(statement, scale) for statement in repeated),
        identical=sum(len(set(statement)) == 1 for statement in repeated),
        wide=sum(max(statement) - min(statement) >= WIDE_RANGE for statement in repeated),
        wide_range=WIDE_RANGE,
        statements=len(repeated),
        icc=icc_one_way([[float(rating) for rating in statement] for statement in ratings.values()]),
    )


def axis_profile(
    model: ModelId,
    axis: AxisKey,
    records: Sequence[TrialRecord],
    scores: Sequence[QuestionScore],
    facets: Sequence[FacetScore],
    questionnaire: Questionnaire,
    scale: Scale,
) -> AxisProfile:
    """`records` are every model's; `scores` and `facets` are the model's own; `scale` is the one asked on."""
    ratings = axis_ratings(model, axis, records, questionnaire)
    return AxisProfile(
        ratings=rating_profile([rating for statement in ratings.values() for rating in statement], scale),
        scores=score_split(scores, facets, axis),
        statements=statement_agreement(ratings, scale),
    )


def model_profile(
    model: ModelId,
    records: Sequence[TrialRecord],
    scores: Sequence[QuestionScore],
    facets: Sequence[FacetScore],
    questionnaire: Questionnaire,
    scale: Scale,
) -> AxisPair[AxisProfile]:
    return AxisPair(
        x=axis_profile(model, AxisKey.X, records, scores, facets, questionnaire, scale),
        y=axis_profile(model, AxisKey.Y, records, scores, facets, questionnaire, scale),
    )


def scale_use(first: RatingProfile, second: RatingProfile) -> ScaleUse:
    """Unequal when both spreads are defined, neither is 0, and their ratio reaches SCALE_USE_RATIO."""
    sds = (first.rating_sd, second.rating_sd)
    defined = [sd for sd in sds if sd is not None and sd > 0]
    differs = len(defined) == 2 and max(defined) >= SCALE_USE_RATIO * min(defined)
    return ScaleUse(sd_first=sds[0], sd_second=sds[1], differs=differs)
