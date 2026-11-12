"""Synthetic runs with scripted replies: the schema's example documents, whose digests the version lock holds.

Each scripted model answers with a fixed lean on each axis, so every claim in the examples is known in advance:
- `asserted`: two models, every trial answered; both quadrants and the x ordering are asserted.
- `withheld`: one model whose x interval crosses 0 and that declines a third of its y trials.
- `partial`: the `asserted` models with only the first 60% of the schedule collected, and one orphan.
- `preregistered`: a run whose experiment names a preregistration, so its report is confirmatory; alpha beside
  delta, which shares alpha's lean and drifts a point on one trial in eleven, so both equivalences are asserted, one
  with the ordering; delta's host was listed ten days before the run without its reply schema, two warnings.
- `pooled`: the `asserted` run pooled with a rerun that asks alpha again beside gamma 30 days later, so alpha draws on
  two runs and the pool warns that its runs lie far apart.
- `cross-scale`: the `asserted` models asked under a system prompt on the native scale and on its forced-choice
  form, two pools whose forced-choice one is read against the native one.
"""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity, PolarityPair
from compass_bench.domain.budget import Price, estimate_cost, estimate_prompt_tokens
from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import (
    AnalysisSettings,
    AnswerType,
    Design,
    ExperimentSpec,
    ModelSpec,
    ReasoningEffort,
    Sampling,
    ScaleChoice,
    design_conditions,
    design_prompt,
    effective_scale,
    experiment_hash,
)
from compass_bench.domain.design.factors import (
    DisplayOrder,
    DisplayOrderFactor,
    FactorKind,
    NumericMapping,
    NumericMappingFactor,
    displayed_rating,
)
from compass_bench.domain.design.schedule import Trial, build_schedule
from compass_bench.domain.elicitation.prompts import RATING_MEMBER, STANDARD_PROMPT, Prompt
from compass_bench.domain.ids import EndpointId, ModelId, QuestionId, TrialKey, run_id
from compass_bench.domain.instrument.compass import Axis, Compass
from compass_bench.domain.instrument.questionnaire import (
    Question,
    Questionnaire,
    question_index,
    questionnaire_hash,
    questions_on,
)
from compass_bench.domain.instrument.scale import CanonicalRating, Scale, center, points
from compass_bench.domain.ledger import (
    Attempt,
    AttemptResultKind,
    Completed,
    Finished,
    FinishReason,
    LedgerEntry,
    LedgerEntryKind,
    Orphaned,
    Reply,
    TransportError,
    TransportFailed,
    Usage,
)
from compass_bench.domain.listing import ModelListing
from compass_bench.domain.run import PlannedRun, RunRecord
from compass_bench.domain.stats.seeds import schedule_seed
from compass_bench.domain.value import Value

EXAMPLE_CREATED_AT: Final = datetime(2026, 1, 1, tzinfo=UTC)
EXAMPLE_FINGERPRINT: Final = "fp_example"
EXAMPLE_LISTED_DAYS: Final = 90
# the preregistered example's second model was listed this many days before its run, under FRESH_LISTING_DAYS
FRESH_LISTED_DAYS: Final = 10
# the pooled example's rerun was created this many days after the first run, past REVIEW_AFTER_DAYS, so the pool warns
RERUN_AFTER_DAYS: Final = 30
# the preregistration the preregistered example's experiment names, relative to its experiment file
EXAMPLE_PREREGISTRATION: Final = "../preregistrations/example-2026-01-01.md"
QUESTIONS_PER_AXIS: Final = 12
# added to a model's lean, question by question, so its question scores spread around the lean
QUESTION_OFFSETS: Final = (-0.25, 0.0, 0.25)
COLLECTED_SHARE_OF_PARTIAL_RUN: Final = 0.6
# every this many trials by schedule position, a model's first attempt times out and its retry answers
TIMEOUT_EVERY: Final = 7
DECLINE_EVERY: Final = 3
DECLINE_TEXT: Final = "I can't share personal opinions on political topics."
# every this many trials by schedule position, a free-text model hedges around its number
HEDGE_EVERY: Final = 5
HEDGE_TEXT: Final = "I'd rather not say, but {rating}."
REPORTED_COST_USD: Final = 0.00002
# the cross-scale example asks under a system prompt, so its native pool has a key, and an id, of its own
CROSS_SCALE_SYSTEM_PROMPT: Final = "Answer each statement on its own."
ENDPOINT: Final = EndpointId("openrouter")
# the example endpoint's settings, as a run stores them; the key is named by its variable, never given
EXAMPLE_ENDPOINT: Final = EndpointSettings(
    base_url="https://openrouter.ai/api/v1",
    api_key_env="OPENROUTER_API_KEY",
    max_concurrency=2,
    timeout_seconds=30.0,
    provider_order=("Example",),
    allow_fallbacks=False,
    require_parameters=True,
    quantizations=(),
)


class ScriptedModel(Value):
    """How a synthetic model answers: its lean on each axis in answer-value units, from -1 to +1.

    `offset_shift` rotates QUESTION_OFFSETS, so two models' question scores do not move in lockstep. On every
    `drift_every`-th trial by schedule position the model answers one point further toward the positive pole, so a
    model that shares another's lean differs from it by a small, uneven gap."""

    lean: AxisPair[float]
    answer_type: AnswerType
    offset_shift: int
    declines_on: AxisKey | None
    drift_every: int | None


ALPHA: Final = ScriptedModel(
    lean=AxisPair(x=0.5, y=-0.5), answer_type=AnswerType.FREE_TEXT, offset_shift=0, declines_on=None, drift_every=None
)
BETA: Final = ScriptedModel(
    lean=AxisPair(x=-0.5, y=-0.5),
    answer_type=AnswerType.STRUCTURED,
    offset_shift=1,
    declines_on=None,
    drift_every=None,
)
GAMMA: Final = ScriptedModel(
    lean=AxisPair(x=0.0, y=0.5),
    answer_type=AnswerType.FREE_TEXT,
    offset_shift=0,
    declines_on=AxisKey.Y,
    drift_every=None,
)
# alpha's lean, answered through a reply schema, drifting a point toward the positive pole on one trial in eleven
DELTA: Final = ScriptedModel(
    lean=AxisPair(x=0.5, y=-0.5), answer_type=AnswerType.STRUCTURED, offset_shift=0, declines_on=None, drift_every=11
)


def example_questionnaire() -> Questionnaire:
    compass = Compass(
        axes=AxisPair(
            x=Axis(name="left vs right", negative="left", positive="right"),
            y=Axis(name="libertarian vs authoritarian", negative="libertarian", positive="authoritarian"),
        )
    )
    questions = tuple(
        Question(
            id=QuestionId(f"{axis}-{index:02d}"),
            axis=axis,
            facet=f"{compass.axes.get(axis).name} {'odd' if index % 2 else 'even'}",
            statements=PolarityPair(
                negative=f"Example statement {axis}-{index:02d}, phrased toward {compass.axes.get(axis).negative}.",
                positive=f"Example statement {axis}-{index:02d}, phrased toward {compass.axes.get(axis).positive}.",
            ),
        )
        for axis in AxisKey
        for index in range(QUESTIONS_PER_AXIS)
    )
    labels = ("Strongly disagree", "Disagree", "Neither agree nor disagree", "Agree", "Strongly agree")
    return Questionnaire(
        title="Example compass", compass=compass, scale=Scale(labels=labels), questions=questions, author="Jane Doe"
    )


def model_spec(name: ModelId, scripted: ScriptedModel) -> ModelSpec:
    return ModelSpec(
        endpoint=ENDPOINT,
        model=f"example/{name}",
        sampling=Sampling(temperature=1.0, top_p=None, max_tokens=16, reasoning=ReasoningEffort.OFF),
        answer_type=scripted.answer_type,
        price=Price(prompt_usd_per_million=1.0, completion_usd_per_million=4.0),
    )


def example_spec(
    questionnaire: Questionnaire,
    models: Mapping[ModelId, ScriptedModel],
    scale: ScaleChoice,
    system_prompt: str | None,
    preregistration: str | None,
) -> ExperimentSpec:
    """Both factors at both levels, one repetition, the given scale form, system prompt, and preregistration."""
    design = Design(
        factors=(
            DisplayOrderFactor(kind=FactorKind.DISPLAY_ORDER, levels=tuple(DisplayOrder)),
            NumericMappingFactor(kind=FactorKind.NUMERIC_MAPPING, levels=tuple(NumericMapping)),
        ),
        repetitions_per_condition=1,
        scale=scale,
        system_prompt=system_prompt,
        prompt=STANDARD_PROMPT,
        max_retries=2,
    )
    return ExperimentSpec(
        name="example",
        questionnaire=questionnaire_hash(questionnaire),
        models={name: model_spec(name, scripted) for name, scripted in models.items()},
        design=design,
        analysis=AnalysisSettings(confidence_level=0.95, coverage_floor=0.8, equivalence_margin=0.1),
        preregistration=preregistration,
    )


def example_listing() -> ModelListing:
    """Listed EXAMPLE_LISTED_DAYS before the run on the example host, which supports every sent parameter."""
    return ModelListing(
        listed_at=EXAMPLE_CREATED_AT - timedelta(days=EXAMPLE_LISTED_DAYS),
        host="Example",
        supported_parameters=("temperature", "top_p", "max_tokens", "reasoning", "response_format"),
    )


def fresh_listing() -> ModelListing:
    """Listed FRESH_LISTED_DAYS before the run on a host that does not list a reply schema as supported, so a
    structured model raises both listing warnings."""
    return ModelListing(
        listed_at=EXAMPLE_CREATED_AT - timedelta(days=FRESH_LISTED_DAYS),
        host="Example",
        supported_parameters=("temperature", "top_p", "max_tokens", "reasoning"),
    )


def planned_example(
    name: str,
    models: Mapping[ModelId, ScriptedModel],
    scale: ScaleChoice = ScaleChoice.NATIVE,
    system_prompt: str | None = None,
    preregistration: str | None = None,
    listings: Mapping[ModelId, ModelListing] | None = None,
    created_at: datetime = EXAMPLE_CREATED_AT,
) -> PlannedRun:
    """The run as create_run would store it, under the nonce `example-<name>`; a model `listings` leaves out gets
    example_listing."""
    nonce = f"example-{name}"
    questionnaire = example_questionnaire()
    spec = example_spec(questionnaire, models, scale, system_prompt, preregistration)
    run = run_id(nonce)
    given = listings or {}
    record = RunRecord(
        run_id=run,
        experiment=experiment_hash(spec),
        nonce=nonce,
        code_revision="example",
        listings={model: given.get(model, example_listing()) for model in models},
        created_at=created_at,
    )
    trials = build_schedule(run, spec, questionnaire, schedule_seed(nonce))
    return PlannedRun(run=record, questionnaire=questionnaire, spec=spec, trials=trials)


def question_places(questionnaire: Questionnaire) -> dict[QuestionId, tuple[AxisKey, int]]:
    """Each question's axis and its index among that axis's questions."""
    return {
        question.id: (axis, index)
        for axis in AxisKey
        for index, question in enumerate(questions_on(questionnaire, axis))
    }


def scripted_rating(
    scripted: ScriptedModel, polarity: Polarity, place: tuple[AxisKey, int], scale: Scale
) -> CanonicalRating:
    """The canonical rating whose answer value is nearest the lean plus this question's offset."""
    axis, index = place
    target = scripted.lean.get(axis) + QUESTION_OFFSETS[(index + scripted.offset_shift) % len(QUESTION_OFFSETS)]
    nearest = math.floor(center(scale) + polarity * target * (center(scale) - 1) + 0.5)
    return CanonicalRating(min(max(nearest, 1), points(scale)))


def drifted_rating(scripted: ScriptedModel, trial: Trial, rating: CanonicalRating, scale: Scale) -> CanonicalRating:
    """The rating one point toward the positive pole on a drifting trial, clamped to the scale; else as it is."""
    if scripted.drift_every is None or trial.position % scripted.drift_every != 0:
        return rating
    return CanonicalRating(min(max(rating + trial.polarity, 1), points(scale)))


def reply_text(
    scripted: ScriptedModel, trial: Trial, condition: Condition, place: tuple[AxisKey, int], scale: Scale
) -> str:
    """A decline on every DECLINE_EVERY-th trial of the declined axis, else the rating as the condition shows it.

    A free-text model hedges around its number on every HEDGE_EVERY-th trial."""
    if place[0] is scripted.declines_on and trial.position % DECLINE_EVERY == 0:
        return DECLINE_TEXT
    rating = drifted_rating(scripted, trial, scripted_rating(scripted, trial.polarity, place, scale), scale)
    shown = displayed_rating(scale, condition.numeric_mapping, rating)
    match scripted.answer_type:
        case AnswerType.FREE_TEXT if trial.position % HEDGE_EVERY == 0:
            return HEDGE_TEXT.format(rating=shown)
        case AnswerType.FREE_TEXT:
            return str(shown)
        case AnswerType.STRUCTURED:
            return json.dumps({RATING_MEMBER: shown})


def reply_result(text: str, prompt: Prompt, model: str) -> Completed:
    usage = Usage(
        prompt_tokens=estimate_prompt_tokens(prompt),
        completion_tokens=1,
        reasoning_tokens=0,
        cached_tokens=0,
        cost_usd=REPORTED_COST_USD,
    )
    reply = Reply(
        text=text,
        reasoning=None,
        finish=FinishReason.STOP,
        usage=usage,
        served_model=model,
        served_provider="Example",
        response_id=None,
        created_at=None,
        system_fingerprint=EXAMPLE_FINGERPRINT,
        native_finish_reason="stop",
    )
    return Completed(kind=AttemptResultKind.COMPLETED, reply=reply)


def trial_entries(
    planned: PlannedRun, models: Mapping[ModelId, ScriptedModel], trial: Trial
) -> tuple[LedgerEntry, ...]:
    """The trial's attempts: a timeout and its answered retry every TIMEOUT_EVERY-th trial, else one answer."""
    spec, questionnaire = planned.spec, planned.questionnaire
    scale = effective_scale(spec.design, questionnaire.scale)
    condition = {condition.id: condition for condition in design_conditions(spec.design)}[trial.condition]
    statement = question_index(questionnaire)[trial.question].statements.get(trial.polarity)
    place = question_places(questionnaire)[trial.question]
    model = spec.models[trial.model]
    prompt = design_prompt(spec.design, statement, condition, scale)
    reserved = estimate_cost(prompt, model.sampling.max_tokens, model.price)
    answer = reply_result(reply_text(models[trial.model], trial, condition, place, scale), prompt, model.model)
    received_at = planned.run.created_at + timedelta(seconds=trial.position)
    if trial.position % TIMEOUT_EVERY != 0:
        return (
            Finished(
                kind=LedgerEntryKind.FINISHED,
                attempt=Attempt(trial=trial.key, seq=0, prompt=prompt, reserved_usd=reserved),
                result=answer,
                received_at=received_at,
                in_outage=False,
            ),
        )
    timeout = TransportFailed(
        kind=AttemptResultKind.FAILED, error=TransportError.TIMEOUT, http_status=None, message="no complete response"
    )
    return (
        Finished(
            kind=LedgerEntryKind.FINISHED,
            attempt=Attempt(trial=trial.key, seq=0, prompt=prompt, reserved_usd=reserved),
            result=timeout,
            received_at=received_at,
            in_outage=False,
        ),
        Finished(
            kind=LedgerEntryKind.FINISHED,
            attempt=Attempt(trial=trial.key, seq=1, prompt=prompt, reserved_usd=reserved),
            result=answer,
            received_at=received_at + timedelta(seconds=1),
            in_outage=False,
        ),
    )


def collected_entries(
    planned: PlannedRun, models: Mapping[ModelId, ScriptedModel], collected_share: float
) -> dict[TrialKey, tuple[LedgerEntry, ...]]:
    """Entries for the trials in the first `collected_share` of the schedule; a partial run's next trial is orphaned."""
    collected = math.floor(len(planned.trials) * collected_share)
    entries = {trial.key: trial_entries(planned, models, trial) for trial in planned.trials[:collected]}
    if collected < len(planned.trials):
        orphan = planned.trials[collected]
        sent = trial_entries(planned, models, orphan)[0].attempt
        entries[orphan.key] = (Orphaned(kind=LedgerEntryKind.ORPHANED, attempt=sent),)
    return entries


def example_endpoints() -> dict[EndpointId, EndpointSettings]:
    """The endpoint settings every example run stores: one pinned endpoint."""
    return {ENDPOINT: EXAMPLE_ENDPOINT}


def example_runs() -> dict[str, tuple[PlannedRun, dict[TrialKey, tuple[LedgerEntry, ...]]]]:
    """Each example's planned run and its ledger entries, by example name."""
    pair = {ModelId("alpha"): ALPHA, ModelId("beta"): BETA}
    single = {ModelId("gamma"): GAMMA}
    twins = {ModelId("alpha"): ALPHA, ModelId("delta"): DELTA}
    asserted, withheld, partial = (
        planned_example("asserted", pair),
        planned_example("withheld", single),
        planned_example("partial", pair),
    )
    preregistered = planned_example(
        "preregistered",
        twins,
        preregistration=EXAMPLE_PREREGISTRATION,
        listings={ModelId("delta"): fresh_listing()},
    )
    return {
        "asserted": (asserted, collected_entries(asserted, pair, collected_share=1.0)),
        "withheld": (withheld, collected_entries(withheld, single, collected_share=1.0)),
        "partial": (partial, collected_entries(partial, pair, collected_share=COLLECTED_SHARE_OF_PARTIAL_RUN)),
        "preregistered": (preregistered, collected_entries(preregistered, twins, collected_share=1.0)),
    }


def pooled_example_runs() -> dict[str, tuple[tuple[PlannedRun, dict[TrialKey, tuple[LedgerEntry, ...]]], ...]]:
    """Each pooled example's runs and their entries, by example name."""
    rerun_models = {ModelId("alpha"): ALPHA, ModelId("gamma"): GAMMA}
    rerun = planned_example("rerun", rerun_models, created_at=EXAMPLE_CREATED_AT + timedelta(days=RERUN_AFTER_DAYS))
    rerun_entries = collected_entries(rerun, rerun_models, collected_share=1.0)
    pair = {ModelId("alpha"): ALPHA, ModelId("beta"): BETA}
    native = planned_example("native", pair, ScaleChoice.NATIVE, CROSS_SCALE_SYSTEM_PROMPT)
    native_entries = collected_entries(native, pair, collected_share=1.0)
    forced = planned_example("forced", pair, ScaleChoice.FORCED_CHOICE, CROSS_SCALE_SYSTEM_PROMPT)
    forced_entries = collected_entries(forced, pair, collected_share=1.0)
    return {
        "pooled": (example_runs()["asserted"], (rerun, rerun_entries)),
        "cross-scale": ((native, native_entries), (forced, forced_entries)),
    }
