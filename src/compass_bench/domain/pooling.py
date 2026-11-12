"""Pools: the runs whose answers combine into one report.

Runs pool when they ask the same questionnaire on the same scale under the same analysis settings; their wordings
and presentations average out, as conditions do within a run. A model in several runs of a pool pools its answers,
so its settings, price aside, must match across them.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Final

from compass_bench.domain.analysis import REVIEW_AFTER_DAYS, AnalysisResult, analyze_runs, trial_records
from compass_bench.domain.axis_pair import AxisKey, AxisPair
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import AnalysisSettings, ExperimentSpec, ScaleChoice, effective_scale
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import (
    EndpointId,
    ModelId,
    PoolId,
    QuestionId,
    QuestionnaireHash,
    RunId,
    TrialKey,
    content_hash,
)
from compass_bench.domain.ledger import LedgerEntry
from compass_bench.domain.run import PlannedRun, RunRecord
from compass_bench.domain.scoring import phrasing_values, question_scores
from compass_bench.domain.stats.icc import ReliabilityBand, icc_consistency, reliability_band
from compass_bench.domain.value import Value

type RunEntries = Mapping[TrialKey, Sequence[LedgerEntry]]
# each model's reliability between its runs, per axis
type PoolReliability = Mapping[ModelId, AxisPair[RunReliability | None]]
# a pool's key, its runs in creation order, the analysis of their pooled answers, and the reliability between runs
type PooledAnalysis = tuple[PoolKey, tuple[PlannedRun, ...], AnalysisResult, PoolReliability]

POOL_ID_LENGTH: Final = 12
# a forced-choice position from a model that answered the native scale's midpoint this often is forced, not held:
# a reading convention after Khan, Casper & Hadfield-Menell (2025), who saw a model with no preference on a
# 5-point scale produce a full ranking once the midpoint was removed
MIDPOINT_SHARE_FLOOR: Final = 0.5
# a model's settings that do not change its answers, so they may differ between pooled runs
IGNORED_MODEL_SETTINGS: Final = frozenset({"price"})


class PoolKey(Value):
    """A run's system prompt names the asker its models answered, and its template how they were told to answer,
    so runs under different ones never pool; the instruction wordings do pool, as cells of one design."""

    questionnaire: QuestionnaireHash
    scale: ScaleChoice
    analysis: AnalysisSettings
    system_prompt: str | None
    template: str


class RunReliability(Value):
    """How alike a model's question scores on one axis come out across its runs of the pool.

    `icc` is ICC(3,1) over the questions every run scored, with the runs as the repeated measures: 1 when the
    runs order the questions alike and differ by at most a shift, 0 when they agree no more than chance, below 0
    when they disagree. `band` reads the point estimate on Koo and Li's (2016) bands, which they apply to an
    absolute-agreement ICC's 95% interval. It needs two scored questions and two runs."""

    icc: float
    band: ReliabilityBand
    questions: int
    runs: int


class ModelSettingsDiffer(Exception):
    """One model id was asked with different settings in two runs of a pool, so its answers do not combine."""


def pool_key(spec: ExperimentSpec) -> PoolKey:
    return PoolKey(
        questionnaire=spec.questionnaire,
        scale=spec.design.scale,
        analysis=spec.analysis,
        system_prompt=spec.design.system_prompt,
        template=spec.design.prompt.template,
    )


def pool_id(key: PoolKey) -> PoolId:
    """12 hex digits of the key's content hash, so a pool keeps its id however many runs join it."""
    return PoolId(content_hash(["pool", key.model_dump(mode="json")])[:POOL_ID_LENGTH])


def pools(runs: Sequence[PlannedRun]) -> dict[PoolKey, tuple[PlannedRun, ...]]:
    """The runs grouped by pool key, each pool's runs in creation order."""
    grouped: defaultdict[PoolKey, list[PlannedRun]] = defaultdict(list)
    for planned in sorted(runs, key=lambda planned: (planned.run.created_at, planned.run.run_id)):
        grouped[pool_key(planned.spec)].append(planned)
    return {key: tuple(members) for key, members in grouped.items()}


def check_model_settings(runs: Sequence[PlannedRun]) -> None:
    """Raise ModelSettingsDiffer when a model id carries different settings, price aside, in two of the runs."""
    first_seen: dict[ModelId, tuple[RunId, object]] = {}
    for planned in runs:
        for model, spec in planned.spec.models.items():
            settings = spec.model_dump(mode="json", exclude=set(IGNORED_MODEL_SETTINGS))
            run, seen = first_seen.setdefault(model, (planned.run.run_id, settings))
            if seen != settings:
                raise ModelSettingsDiffer(
                    f"model {model} has different settings in runs {run} and {planned.run.run_id}; "
                    "give one of them its own catalog name"
                )
    return


def analyze_pool(key: PoolKey, runs: Sequence[tuple[PlannedRun, RunEntries]]) -> AnalysisResult:
    """Every run's answers pooled under the pool's analysis settings; raises ModelSettingsDiffer first."""
    check_model_settings([planned for planned, _ in runs])
    ledgers = [(planned.trials, entries, planned.spec) for planned, entries in runs]
    return analyze_runs(ledgers, runs[0][0].questionnaire, key.analysis)


def run_scores(planned: PlannedRun, entries: RunEntries) -> Mapping[ModelId, Mapping[QuestionId, float]]:
    """Each model's question scores from this run's answers alone, by question."""
    questionnaire = planned.questionnaire
    records = trial_records(planned.trials, entries, questionnaire, planned.spec)
    values = phrasing_values(records, effective_scale(planned.spec.design, questionnaire.scale))
    scores = question_scores(values, questionnaire, sorted(planned.spec.models))
    return {model: {score.question: score.score for score in model_scores} for model, model_scores in scores.items()}


def axis_reliability(
    axis: AxisKey, scores: Sequence[Mapping[QuestionId, float]], questions: Sequence[QuestionId]
) -> RunReliability | None:
    """ICC(3,1) over the axis's questions every run scored; None below two runs, two such questions, or spread."""
    shared = [question for question in questions if all(question in run for run in scores)]
    rows = [[run[question] for run in scores] for question in shared]
    icc = icc_consistency(rows) if len(scores) >= 2 else None
    if icc is None:
        return None
    return RunReliability(icc=icc, band=reliability_band(icc), questions=len(shared), runs=len(scores))


def pool_reliability(runs: Sequence[tuple[PlannedRun, RunEntries]]) -> PoolReliability:
    """Each model's reliability between the runs that asked it; None for a model asked in one run."""
    questionnaire = runs[0][0].questionnaire
    by_axis = {axis: [question.id for question in questionnaire.questions if question.axis is axis] for axis in AxisKey}
    per_run = [run_scores(planned, entries) for planned, entries in runs]
    models = sorted({model for scores in per_run for model in scores})
    return {
        model: AxisPair(
            x=axis_reliability(AxisKey.X, [scores[model] for scores in per_run if model in scores], by_axis[AxisKey.X]),
            y=axis_reliability(AxisKey.Y, [scores[model] for scores in per_run if model in scores], by_axis[AxisKey.Y]),
        )
        for model in models
    }


def pool_order(key: PoolKey) -> tuple[int, PoolId]:
    """Pools sort by scale, in ScaleChoice order, then by id."""
    return list(ScaleChoice).index(key.scale), pool_id(key)


def pooled_analyses(runs: Sequence[tuple[PlannedRun, RunEntries]]) -> tuple[PooledAnalysis, ...]:
    """Each pool of the runs, with its runs in creation order and its analysis; raises ModelSettingsDiffer."""
    entries = {planned.run.run_id: run_entries for planned, run_entries in runs}
    grouped = pools([planned for planned, _ in runs])
    analyses: list[PooledAnalysis] = []
    for key, members in sorted(grouped.items(), key=lambda item: pool_order(item[0])):
        pool_runs = [(planned, entries[planned.run.run_id]) for planned in members]
        analyses.append((key, members, analyze_pool(key, pool_runs), pool_reliability(pool_runs)))
    return tuple(analyses)


def served_findings(result: AnalysisResult) -> tuple[Finding, ...]:
    """A warning per model whose replies name more than one served model string."""
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.MIXED_SERVED_MODELS,
            message=f"model {model.model!r} was served as {', '.join(model.served)}; its pooled answers may come "
            "from different versions",
        )
        for model in result.models
        if len(model.served) > 1
    )


def span_findings(records: Sequence[RunRecord]) -> tuple[Finding, ...]:
    """A warning when the pool's runs were created REVIEW_AFTER_DAYS or more apart."""
    if len(records) < 2:
        return ()
    span = max(record.created_at for record in records) - min(record.created_at for record in records)
    if span < timedelta(days=REVIEW_AFTER_DAYS):
        return ()
    return (
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.RUNS_FAR_APART,
            message=f"the pool's runs were created {span.days} days apart; a hosted model can change between them",
        ),
    )


def routing_findings(
    runs: Sequence[PlannedRun], endpoints: Mapping[RunId, Mapping[EndpointId, EndpointSettings]]
) -> tuple[Finding, ...]:
    """A warning per model whose runs pinned different host orders or precision filters for its endpoint.

    `check_model_settings` holds a model's own settings equal across its runs; the endpoint's routing is stored per
    run, so it can differ under one endpoint id, and a pooled position then draws on two hosts."""
    routings: defaultdict[ModelId, dict[tuple[tuple[str, ...], tuple[str, ...]], RunId]] = defaultdict(dict)
    for planned in runs:
        for model, spec in planned.spec.models.items():
            endpoint = endpoints[planned.run.run_id].get(spec.endpoint)
            if endpoint is not None:
                routing = (endpoint.provider_order, endpoint.quantizations)
                routings[model].setdefault(routing, planned.run.run_id)
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.MIXED_ROUTING,
            message=f"model {model!r} was asked through different host orders or precision filters in runs "
            f"{', '.join(seen.values())}; its pooled answers may come from different hosts",
        )
        for model, seen in sorted(routings.items())
        if len(seen) > 1
    )


def pool_findings(
    records: Sequence[RunRecord],
    result: AnalysisResult,
    runs: Sequence[PlannedRun] = (),
    endpoints: Mapping[RunId, Mapping[EndpointId, EndpointSettings]] | None = None,
) -> tuple[Finding, ...]:
    """The warnings a pool raises: mixed served model strings, runs far apart in time, and mixed routing."""
    routing = routing_findings(runs, endpoints) if endpoints is not None else ()
    return served_findings(result) + span_findings(records) + routing


class ScaleReference(Value):
    """A forced-choice pool's model read against the same model's native-scale pool.

    `midpoint_share` is the share of the model's native-scale answers at the midpoint, per axis; `forced_not_held`
    is whether that share reaches MIDPOINT_SHARE_FLOOR, so the forced-choice position comes from answers the
    midpoint would have absorbed. Both are None or False on an axis the native pool did not score."""

    native_pool: PoolId
    midpoint_share: AxisPair[float | None]
    forced_not_held: AxisPair[bool]


def native_key(key: PoolKey) -> PoolKey:
    """The pool key of the same questionnaire, settings, system prompt, and template on the native scale."""
    return key.model_copy(update={"scale": ScaleChoice.NATIVE})


def midpoint_shares(result: AnalysisResult) -> dict[ModelId, AxisPair[float | None]]:
    return {
        model.model: AxisPair(x=model.profile.x.ratings.midpoint_share, y=model.profile.y.ratings.midpoint_share)
        for model in result.models
    }


def scale_reference(native: PoolId, shares: AxisPair[float | None]) -> ScaleReference:
    return ScaleReference(
        native_pool=native,
        midpoint_share=shares,
        forced_not_held=AxisPair(
            x=shares.x is not None and shares.x >= MIDPOINT_SHARE_FLOOR,
            y=shares.y is not None and shares.y >= MIDPOINT_SHARE_FLOOR,
        ),
    )


def scale_references(analyses: Sequence[PooledAnalysis]) -> dict[PoolKey, dict[ModelId, ScaleReference]]:
    """For each forced-choice pool with a native counterpart among `analyses`, each shared model's reference."""
    natives = {key: result for key, _, result, _ in analyses if key.scale is ScaleChoice.NATIVE}
    references: dict[PoolKey, dict[ModelId, ScaleReference]] = {}
    for key, _, result, _ in analyses:
        if key.scale is ScaleChoice.NATIVE or native_key(key) not in natives:
            continue
        shares = midpoint_shares(natives[native_key(key)])
        native = pool_id(native_key(key))
        references[key] = {
            model.model: scale_reference(native, shares[model.model])
            for model in result.models
            if model.model in shares
        }
    return references


def model_runs(runs: Sequence[PlannedRun]) -> dict[ModelId, tuple[RunId, ...]]:
    """Each model of the runs, in id order, with the runs that asked it, in the runs' order."""
    asked: defaultdict[ModelId, list[RunId]] = defaultdict(list)
    for planned in runs:
        for model in planned.spec.models:
            asked[model].append(planned.run.run_id)
    return {model: tuple(asked[model]) for model in sorted(asked)}
