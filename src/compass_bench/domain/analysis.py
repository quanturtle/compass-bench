"""The analysis pipeline: read, score questions, place each model, compare pairs, claim. Pure and repeatable."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair
from compass_bench.domain.claims import (
    EquivalenceClaim,
    OrderingClaim,
    PairOutcome,
    QuadrantClaim,
    equivalence_claims,
    ordering_claims,
    pair_outcomes,
    quadrant_claim,
)
from compass_bench.domain.consistency import AxisConsistency, CellValues, cell_values, model_consistency, pooled_cells
from compass_bench.domain.design.experiment import AnalysisSettings, ExperimentSpec, design_conditions, effective_scale
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.ids import ModelId, TrialKey
from compass_bench.domain.inference import AxisPosition, PairAxis, axis_position, pair_axes, position_level
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.ledger import Completed, Finished, LedgerEntry
from compass_bench.domain.missing import AxisUnanswered, Bound, model_unanswered, pair_bounds
from compass_bench.domain.outcome import LossReason, Lost, Pending, Replied, TrialRecord, fold_outcome
from compass_bench.domain.profile import AxisProfile, ScaleUse, model_profile, scale_use
from compass_bench.domain.reading.reading import (
    DeclineRead,
    FormatFailure,
    FormatFailureKind,
    RatingRead,
    ReadContext,
)
from compass_bench.domain.robustness import OrderingRobustness, pair_robustness
from compass_bench.domain.scoring import (
    FacetScore,
    PhrasingKey,
    QuestionScore,
    axis_coverage,
    facet_scores,
    phrasing_values,
    pooled_values,
    question_scores,
)
from compass_bench.domain.value import Value

# one run's trials, its ledger entries by trial, and the experiment it ran
type RunLedger = tuple[Sequence[Trial], Mapping[TrialKey, Sequence[LedgerEntry]], ExperimentSpec]


class OutcomeCounts(Value):
    """How a model's trials ended; `hedged` counts the answered trials whose reply also carried decline wording."""

    answered: int
    hedged: int
    declined: int
    format_failed: Mapping[FormatFailureKind, int]
    lost: Mapping[LossReason, int]
    pending: int


class ModelUsage(Value):
    """`completed` counts the attempts that got a reply, and `reasoning_replies` those whose reply carried reasoning
    tokens, so an endpoint that asked for reasoning and got none shows it."""

    attempts: int
    retries: int
    completed: int
    reasoning_replies: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float
    unpriced_attempts: int


class ModelResult(Value):
    """Everything the report says about one model: its question scores, its position per axis, its quadrant,
    and the consistency diagnostics behind the position.

    `hosts`, `served`, and `fingerprints` count the model's replied trials per upstream host, per model string the
    endpoint reported serving, and per system fingerprint, each with `unknown` for a reply that reported none.
    `first_reply_at` and `last_reply_at` bound when the ledger received the model's replies; None without one."""

    model: ModelId
    questions: tuple[QuestionScore, ...]
    facets: tuple[FacetScore, ...]
    axes: AxisPair[AxisPosition]
    quadrant: QuadrantClaim
    consistency: AxisPair[AxisConsistency]
    unanswered: AxisPair[AxisUnanswered]
    profile: AxisPair[AxisProfile]
    outcomes: OutcomeCounts
    hosts: Mapping[str, int]
    served: Mapping[str, int]
    fingerprints: Mapping[str, int]
    first_reply_at: datetime | None
    last_reply_at: datetime | None
    review_after: datetime | None
    usage: ModelUsage


class PairResult(Value):
    """Everything the report says about two models, in canonical model-id order: each axis's gap, its bound under
    any answers to the unanswered trials, how many cells keep its sign, whether the two use the scale unequally,
    ordering, equivalence, and the reading of the two claims together."""

    first: ModelId
    second: ModelId
    axes: AxisPair[PairAxis]
    bounds: AxisPair[Bound | None]
    robustness: AxisPair[OrderingRobustness | None]
    scale_use: AxisPair[ScaleUse]
    orderings: AxisPair[OrderingClaim]
    equivalences: AxisPair[EquivalenceClaim]
    outcomes: AxisPair[PairOutcome]


class AnalysisResult(Value):
    models: tuple[ModelResult, ...]
    pairs: tuple[PairResult, ...]


def trial_records(
    trials: Sequence[Trial],
    entries: Mapping[TrialKey, Sequence[LedgerEntry]],
    questionnaire: Questionnaire,
    spec: ExperimentSpec,
) -> tuple[TrialRecord, ...]:
    """Each trial's outcome, read on the scale it was asked on under its own condition; no entries is Pending."""
    scale = effective_scale(spec.design, questionnaire.scale)
    conditions = {condition.id: condition for condition in design_conditions(spec.design)}
    return tuple(
        TrialRecord(
            trial=trial,
            outcome=fold_outcome(
                entries.get(trial.key, ()),
                spec.models[trial.model],
                ReadContext(scale=scale, condition=conditions[trial.condition]),
                spec.design,
            ),
        )
        for trial in trials
    )


def outcome_counts(records: Iterable[TrialRecord]) -> OutcomeCounts:
    """Over one model's trial records; every failure and loss kind is listed, zeros included."""
    outcomes = [record.outcome for record in records]
    readings = [outcome.reading for outcome in outcomes if isinstance(outcome, Replied)]
    failures = Counter(reading.failure for reading in readings if isinstance(reading, FormatFailure))
    losses = Counter(outcome.loss for outcome in outcomes if isinstance(outcome, Lost))
    ratings = [reading for reading in readings if isinstance(reading, RatingRead)]
    return OutcomeCounts(
        answered=len(ratings),
        hedged=sum(rating.hedge is not None for rating in ratings),
        declined=sum(isinstance(reading, DeclineRead) for reading in readings),
        format_failed={kind: failures[kind] for kind in FormatFailureKind},
        lost={reason: losses[reason] for reason in LossReason},
        pending=sum(isinstance(outcome, Pending) for outcome in outcomes),
    )


UNKNOWN_HOST: Final = "unknown"
# a hosted model can change under one name; a position older than this many days is due a re-check
REVIEW_AFTER_DAYS: Final = 28


def review_after(last_reply_at: datetime | None) -> datetime | None:
    """When a model's position is due a re-check: REVIEW_AFTER_DAYS after its last reply; None without one."""
    return None if last_reply_at is None else last_reply_at + timedelta(days=REVIEW_AFTER_DAYS)


def model_hosts(records: Iterable[TrialRecord]) -> dict[str, int]:
    """Replied trials per upstream host, in host order; a reply without a reported host counts under `unknown`."""
    hosts = Counter(record.outcome.host or UNKNOWN_HOST for record in records if isinstance(record.outcome, Replied))
    return dict(sorted(hosts.items()))


def model_served(records: Iterable[TrialRecord]) -> dict[str, int]:
    """Replied trials per model string the endpoint reported serving, `unknown` when it reported none."""
    served = Counter(
        record.outcome.served_model or UNKNOWN_HOST for record in records if isinstance(record.outcome, Replied)
    )
    return dict(sorted(served.items()))


def model_fingerprints(records: Iterable[TrialRecord]) -> dict[str, int]:
    """Replied trials per system fingerprint, `unknown` when the reply carried none."""
    fingerprints = Counter(
        record.outcome.fingerprint or UNKNOWN_HOST for record in records if isinstance(record.outcome, Replied)
    )
    return dict(sorted(fingerprints.items()))


def reply_span(entries: Iterable[LedgerEntry]) -> tuple[datetime | None, datetime | None]:
    """When the ledger received the first and the last completed reply among the entries; None without one."""
    received = [
        entry.received_at for entry in entries if isinstance(entry, Finished) and isinstance(entry.result, Completed)
    ]
    return (min(received), max(received)) if received else (None, None)


def reported_cost(entry: LedgerEntry) -> float | None:
    """The cost the provider reported for a completed reply; a failure or an orphan has none."""
    match entry:
        case Finished(result=Completed(reply=reply)):
            return reply.usage.cost_usd
        case _:
            return None


def model_usage(entries: Iterable[LedgerEntry]) -> ModelUsage:
    """Over one model's ledger entries; every attempt counts, and every seq after 0 is a retry.

    `cost_usd` sums the costs the provider reported, and `unpriced_attempts` counts the attempts without one."""
    attempts = list(entries)
    usages = [
        entry.result.reply.usage
        for entry in attempts
        if isinstance(entry, Finished) and isinstance(entry.result, Completed)
    ]
    costs = [reported_cost(entry) for entry in attempts]
    return ModelUsage(
        attempts=len(attempts),
        retries=sum(entry.attempt.seq > 0 for entry in attempts),
        completed=len(usages),
        reasoning_replies=sum(usage.reasoning_tokens > 0 for usage in usages),
        prompt_tokens=sum(usage.prompt_tokens for usage in usages),
        completion_tokens=sum(usage.completion_tokens for usage in usages),
        reasoning_tokens=sum(usage.reasoning_tokens for usage in usages),
        cost_usd=sum(cost for cost in costs if cost is not None),
        unpriced_attempts=sum(cost is None for cost in costs),
    )


def model_axes(
    scores: Sequence[QuestionScore], coverage: AxisPair[float], settings: AnalysisSettings
) -> AxisPair[AxisPosition]:
    return AxisPair(
        x=axis_position(scores, AxisKey.X, coverage.x, settings),
        y=axis_position(scores, AxisKey.Y, coverage.y, settings),
    )


def model_result(
    model: ModelId,
    records: Sequence[TrialRecord],
    entries: Sequence[LedgerEntry],
    scores: Sequence[QuestionScore],
    facets: tuple[FacetScore, ...],
    axes: AxisPair[AxisPosition],
    consistency: AxisPair[AxisConsistency],
    unanswered: AxisPair[AxisUnanswered],
    profile: AxisPair[AxisProfile],
    settings: AnalysisSettings,
) -> ModelResult:
    """Everything about one model; `records` and `entries` are its own."""
    outcomes = outcome_counts(records)
    first_reply_at, last_reply_at = reply_span(entries)
    return ModelResult(
        model=model,
        questions=tuple(scores),
        facets=facets,
        axes=axes,
        quadrant=quadrant_claim(model, axes, settings, outcomes.pending),
        consistency=consistency,
        unanswered=unanswered,
        profile=profile,
        outcomes=outcomes,
        hosts=model_hosts(records),
        served=model_served(records),
        fingerprints=model_fingerprints(records),
        first_reply_at=first_reply_at,
        last_reply_at=last_reply_at,
        review_after=review_after(last_reply_at),
        usage=model_usage(entries),
    )


def run_values(
    runs: Sequence[RunLedger], records: Sequence[Sequence[TrialRecord]], questionnaire: Questionnaire
) -> dict[PhrasingKey, list[float]]:
    """Each run's answer values on the scale it asked on, pooled per model, question, and phrasing."""
    return pooled_values(
        phrasing_values(run_records, effective_scale(spec.design, questionnaire.scale))
        for (_, _, spec), run_records in zip(runs, records, strict=True)
    )


def run_cells(
    runs: Sequence[RunLedger], records: Sequence[Sequence[TrialRecord]], questionnaire: Questionnaire
) -> CellValues:
    """The same answer values split by cell, each run's under its own conditions, pooled across runs by cell."""
    return pooled_cells(
        [
            cell_values(
                run_records,
                {condition.id: condition for condition in design_conditions(spec.design)},
                effective_scale(spec.design, questionnaire.scale),
            )
            for (_, _, spec), run_records in zip(runs, records, strict=True)
        ]
    )


def analyze_runs(runs: Sequence[RunLedger], questionnaire: Questionnaire, settings: AnalysisSettings) -> AnalysisResult:
    """The runs' answers pooled per question: each read under its own run's design and valued on its own scale.

    A model in several runs pools its answers, each counting once; pending trials in any run withhold claims."""
    per_run = [trial_records(trials, entries, questionnaire, spec) for trials, entries, spec in runs]
    records = [record for run_records in per_run for record in run_records]
    models = sorted({model for _, _, spec in runs for model in spec.models})
    values = run_values(runs, per_run, questionnaire)
    cells = run_cells(runs, per_run, questionnaire)
    scores = question_scores(values, questionnaire, models)
    facets = {model: facet_scores(scores[model], questionnaire) for model in models}
    coverage = axis_coverage(records, questionnaire)
    axes = {model: model_axes(scores[model], coverage[model], settings) for model in models}
    # the runs of a pool ask on one scale choice, so the first run's effective scale is every run's
    scale = effective_scale(runs[0][2].design, questionnaire.scale)
    pending = sum(isinstance(record.outcome, Pending) for record in records)
    profiles = {
        model: model_profile(model, records, scores[model], facets[model], questionnaire, scale) for model in models
    }
    results = tuple(
        model_result(
            model,
            [record for record in records if record.trial.model == model],
            [
                entry
                for trials, entries, _ in runs
                for trial in trials
                if trial.model == model
                for entry in entries.get(trial.key, ())
            ],
            scores[model],
            facets[model],
            axes[model],
            model_consistency(model, values, cells, questionnaire),
            model_unanswered(model, values, records, scores[model], questionnaire, position_level(settings)),
            profiles[model],
            settings,
        )
        for model in models
    )
    pairs = tuple(
        pair_result(
            first,
            second,
            pair,
            pair_bounds(first, second, values, records, questionnaire),
            pair_robustness(first, second, pair, cells, questionnaire),
            pair_scale_use(profiles[first], profiles[second]),
            axes[first],
            axes[second],
            settings,
            pending,
        )
        for (first, second), pair in pair_axes(scores, settings).items()
    )
    return AnalysisResult(models=results, pairs=pairs)


def pair_scale_use(first: AxisPair[AxisProfile], second: AxisPair[AxisProfile]) -> AxisPair[ScaleUse]:
    """Whether the two models use the scale unequally on each axis, from their rating spreads."""
    return AxisPair(
        x=scale_use(first.x.ratings, second.x.ratings),
        y=scale_use(first.y.ratings, second.y.ratings),
    )


def pair_result(
    first: ModelId,
    second: ModelId,
    pair: AxisPair[PairAxis],
    bounds: AxisPair[Bound | None],
    robustness: AxisPair[OrderingRobustness | None],
    use: AxisPair[ScaleUse],
    first_axes: AxisPair[AxisPosition],
    second_axes: AxisPair[AxisPosition],
    settings: AnalysisSettings,
    pending: int,
) -> PairResult:
    orderings = ordering_claims(pair, first, first_axes, second, second_axes, settings, pending)
    equivalences = equivalence_claims(pair, first, first_axes, second, second_axes, settings, pending)
    return PairResult(
        first=first,
        second=second,
        axes=pair,
        bounds=bounds,
        robustness=robustness,
        scale_use=use,
        orderings=orderings,
        equivalences=equivalences,
        outcomes=pair_outcomes(orderings, equivalences),
    )


def analyze(
    trials: Sequence[Trial],
    entries: Mapping[TrialKey, Sequence[LedgerEntry]],
    questionnaire: Questionnaire,
    spec: ExperimentSpec,
) -> AnalysisResult:
    """A partial run is analyzable; missing trials show as coverage and run_incomplete, never as an error."""
    return analyze_runs(((trials, entries, spec),), questionnaire, spec.analysis)
