"""Report document, under compass-bench's one version (compass_bench.version).

It composes domain values directly. A domain change that alters the schema fails tests/test_schema.py, and any change
to the schema or to an example report needs the next version. A report is upgraded by exporting the run again.
"""

from collections.abc import Mapping, Sequence

from compass_bench.domain.analysis import AnalysisResult
from compass_bench.domain.axis_pair import AxisPair
from compass_bench.domain.design.configuration import PairElicitation, pair_elicitations
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import AnalysisSettings, ExperimentSpec, ModelSpec, ScaleChoice
from compass_bench.domain.design.preregistration import ReportStatus, pool_status, run_status
from compass_bench.domain.findings import Finding
from compass_bench.domain.ids import EndpointId, ModelId, PoolId, RunId
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.listing import listing_findings
from compass_bench.domain.pooling import (
    PoolKey,
    PoolReliability,
    RunReliability,
    ScaleReference,
    model_runs,
    pool_findings,
    pool_id,
)
from compass_bench.domain.run import PlannedRun, RunRecord
from compass_bench.domain.value import Value
from compass_bench.version import Version

type Endpoints = Mapping[EndpointId, EndpointSettings]


class ReportDocument(Value):
    """`run` is the run the report derives from; the document is built on demand and stored nowhere.

    `status` is confirmatory only when the stored spec names a preregistration. `endpoints` are the run's endpoint
    settings as stored, by the ids `experiment.models` name. `elicitations` say for each pair of models which
    elicitation fields differ between them. `findings` are the warnings the run's model listings raise: a missing
    listing, a sent parameter the pinned host does not list, or a slug listed shortly before the run."""

    version: Version
    status: ReportStatus
    run: RunRecord
    questionnaire: Questionnaire
    experiment: ExperimentSpec
    endpoints: Endpoints
    elicitations: tuple[PairElicitation, ...]
    result: AnalysisResult
    findings: tuple[Finding, ...]


class PooledRun(Value):
    """A run of the pool, the experiment it ran, and its endpoint settings."""

    run: RunRecord
    experiment: ExperimentSpec
    endpoints: Endpoints


class PooledModel(Value):
    """A model of the pool, the runs its answers come from, in creation order, and how alike its question scores
    came out across them; `reliability` is None on an axis for a model asked in one run.

    `scale_reference` reads a forced-choice pool's model against its native-scale pool; None on a native pool or
    when the model has no native-scale pool of the same questionnaire, settings, and system prompt."""

    model: ModelId
    runs: tuple[RunId, ...]
    reliability: AxisPair[RunReliability | None]
    scale_reference: ScaleReference | None


class PooledReportDocument(Value):
    """One questionnaire's report over every run of a pool: same scale, same analysis settings.

    Each model's answers from all its runs pool per question; built on demand and stored nowhere. `status` is
    confirmatory only when every run names a preregistration. `elicitations` compare each pair of the pool's
    models under the settings of the first run that asked each."""

    version: Version
    status: ReportStatus
    pool: PoolId
    questionnaire: Questionnaire
    scale: ScaleChoice
    analysis: AnalysisSettings
    system_prompt: str | None
    runs: tuple[PooledRun, ...]
    models: tuple[PooledModel, ...]
    elicitations: tuple[PairElicitation, ...]
    result: AnalysisResult
    findings: tuple[Finding, ...]


def report_document(planned: PlannedRun, endpoints: Endpoints, result: AnalysisResult) -> ReportDocument:
    """The document of a run's analysis under the current version; `endpoints` are the run's stored settings."""
    return ReportDocument(
        version=Version.CURRENT,
        status=run_status(planned.spec),
        run=planned.run,
        questionnaire=planned.questionnaire,
        experiment=planned.spec,
        endpoints=endpoints,
        elicitations=pair_elicitations(planned.spec.models, endpoints),
        result=result,
        findings=listing_findings(planned.spec, planned.run.listings, planned.run.created_at),
    )


def pooled_elicitations(runs: Sequence[PooledRun]) -> tuple[PairElicitation, ...]:
    """Each pair of the pool's models compared under the first run that asked each model."""
    models: dict[ModelId, ModelSpec] = {}
    endpoints: dict[EndpointId, EndpointSettings] = {}
    for pooled in runs:
        for name, model in pooled.experiment.models.items():
            if name not in models:
                models[name] = model
                endpoints.setdefault(model.endpoint, pooled.endpoints[model.endpoint])
    return pair_elicitations(models, endpoints)


def pooled_report_document(
    key: PoolKey,
    runs: Sequence[PlannedRun],
    endpoints: Mapping[RunId, Endpoints],
    result: AnalysisResult,
    reliability: PoolReliability,
    references: Mapping[ModelId, ScaleReference],
) -> PooledReportDocument:
    """The document of a pool's analysis under the current version; `runs` are the pool's, in creation order.

    `endpoints` are each run's stored settings; `references` are the pool's scale references by model, empty for
    a native pool."""
    pooled_runs = tuple(
        PooledRun(run=planned.run, experiment=planned.spec, endpoints=endpoints[planned.run.run_id]) for planned in runs
    )
    return PooledReportDocument(
        version=Version.CURRENT,
        status=pool_status(planned.spec for planned in runs),
        pool=pool_id(key),
        questionnaire=runs[0].questionnaire,
        scale=key.scale,
        analysis=key.analysis,
        system_prompt=key.system_prompt,
        runs=pooled_runs,
        elicitations=pooled_elicitations(pooled_runs),
        models=tuple(
            PooledModel(model=model, runs=asked, reliability=reliability[model], scale_reference=references.get(model))
            for model, asked in model_runs(runs).items()
        ),
        result=result,
        findings=pool_findings([planned.run for planned in runs], result, runs, endpoints),
    )
