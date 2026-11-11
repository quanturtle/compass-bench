"""Compile the experiment, catalog, and questionnaire files into one frozen experiment (Builder)."""

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import PurePath

from pydantic import ValidationError

from compass_bench.domain.design.configuration import elicitation_findings
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import (
    AnalysisSettings,
    Design,
    ExperimentSpec,
    ModelSpec,
    canonical_design,
)
from compass_bench.domain.design.factors import factor_findings
from compass_bench.domain.elicitation.prompts import (
    STANDARD_INSTRUCTION,
    STANDARD_TEMPLATE,
    PromptSettings,
    template_findings,
)
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import EndpointId, ModelId
from compass_bench.domain.instrument.questionnaire import Questionnaire, find_problems, questionnaire_hash
from compass_bench.domain.value import Value
from compass_bench.ports.sources import SourceReader


class InvalidExperiment(Exception):
    """The input files do not describe a runnable experiment."""


class Catalog(Value):
    endpoints: Mapping[EndpointId, EndpointSettings]
    models: Mapping[ModelId, ModelSpec]


class PromptFile(PromptSettings):
    """The prompt as an experiment file gives it: an omitted template or instruction is the standard one."""

    template: str = STANDARD_TEMPLATE
    instruction: str = STANDARD_INSTRUCTION


class DesignFile(Design):
    """The design as an experiment file gives it: the prompt may be omitted, in part or whole."""

    prompt: PromptFile = PromptFile()


class ExperimentFile(Value):
    """An omitted `preregistration` means none: the run's claims are exploratory."""

    name: str
    questionnaire: str
    catalog: str
    models: tuple[ModelId, ...]
    design: DesignFile
    analysis: AnalysisSettings
    preregistration: str | None = None


class CompiledExperiment(Value):
    questionnaire: Questionnaire
    spec: ExperimentSpec
    endpoints: Mapping[EndpointId, EndpointSettings]
    findings: tuple[Finding, ...]


def validation_text(error: ValidationError) -> str:
    """Every problem pydantic found, on one line: `design.max_retries: Input should be a valid integer; ...`."""
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or '(document)'}: {detail['msg']}" for detail in error.errors()
    )


def parse_source[M: Value](model: type[M], text: str, path: PurePath) -> M:
    """Validate the source's JSON text; a validation error becomes InvalidExperiment naming the file."""
    try:
        return model.model_validate_json(text)
    except ValidationError as error:
        raise InvalidExperiment(f"{path}: {validation_text(error)}") from error


def read_experiment_file(path: PurePath, sources: SourceReader) -> ExperimentFile:
    return parse_source(ExperimentFile, sources.read_yaml(path), path)


def read_catalog(path: PurePath, sources: SourceReader) -> Catalog:
    return parse_source(Catalog, sources.read_yaml(path), path)


def read_questionnaire(path: PurePath, sources: SourceReader) -> Questionnaire:
    return parse_source(Questionnaire, sources.read_json(path), path)


def resolve_models(names: Sequence[ModelId], catalog: Catalog) -> dict[ModelId, ModelSpec]:
    """The catalog's models under the names the experiment lists; missing_model_findings reports an unknown name."""
    return {name: catalog.models[name] for name in names if name in catalog.models}


def model_endpoints(models: Mapping[ModelId, ModelSpec], catalog: Catalog) -> dict[EndpointId, EndpointSettings]:
    """The catalog endpoints the models use; missing_model_findings reports an unknown endpoint."""
    used = sorted({model.endpoint for model in models.values()})
    return {endpoint: catalog.endpoints[endpoint] for endpoint in used if endpoint in catalog.endpoints}


def model_error(code: FindingCode, message: str) -> Finding:
    return Finding(severity=Severity.ERROR, code=code, message=message)


def duplicate_model_findings(names: Sequence[ModelId]) -> tuple[Finding, ...]:
    counts = Counter(names)
    return tuple(
        model_error(FindingCode.DUPLICATE_MODEL, f"model {name!r} is listed {count} times")
        for name, count in counts.items()
        if count > 1
    )


def missing_model_findings(names: Sequence[ModelId], catalog: Catalog) -> tuple[Finding, ...]:
    """Errors for an empty model list, a name the catalog lacks, and an endpoint the catalog lacks."""
    listed = list(dict.fromkeys(names))
    empty = () if listed else (model_error(FindingCode.NO_MODELS, "the experiment lists no models"),)
    unknown = tuple(
        model_error(FindingCode.UNKNOWN_MODEL, f"model {name!r} is not in the catalog")
        for name in listed
        if name not in catalog.models
    )
    endpoints = tuple(
        model_error(
            FindingCode.UNKNOWN_ENDPOINT,
            f"model {name!r} uses endpoint {catalog.models[name].endpoint!r}, which the catalog does not define",
        )
        for name in listed
        if name in catalog.models and catalog.models[name].endpoint not in catalog.endpoints
    )
    return empty + unknown + endpoints


def pinning_findings(endpoints: Mapping[EndpointId, EndpointSettings]) -> tuple[Finding, ...]:
    """A warning for each used endpoint that lets OpenRouter pick the host: no provider order, or fallbacks on.

    Two hosts of one model can serve different weights or precisions, so a run should ask one host throughout."""
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.UNPINNED_ENDPOINT,
            message=f"endpoint {name!r} lets OpenRouter pick the host, so one run's replies can come from several",
        )
        for name, settings in endpoints.items()
        if not settings.provider_order or settings.allow_fallbacks
    )


def preregistration_findings(path: PurePath, preregistration: str | None, sources: SourceReader) -> tuple[Finding, ...]:
    """An error when the experiment names a preregistration file that is not there, relative to the experiment."""
    if preregistration is None or sources.exists(path.parent / preregistration):
        return ()
    return (
        model_error(
            FindingCode.PREREGISTRATION_MISSING,
            f"preregistration {preregistration!r} is not a file beside the experiment; commit it before the run",
        ),
    )


def spec_design(design: DesignFile) -> Design:
    """The design as the spec holds it: the prompt's values written out, so the hash covers the exact text."""
    prompt = PromptSettings(template=design.prompt.template, instruction=design.prompt.instruction)
    return canonical_design(Design.model_validate({**dict(design), "prompt": prompt}))


def compile_experiment(path: PurePath, sources: SourceReader) -> CompiledExperiment:
    """Paths inside the experiment resolve against its directory; structural findings are returned, not raised."""
    experiment = read_experiment_file(path, sources)
    catalog = read_catalog(path.parent / experiment.catalog, sources)
    questionnaire = read_questionnaire(path.parent / experiment.questionnaire, sources)
    models = resolve_models(experiment.models, catalog)
    spec = ExperimentSpec(
        name=experiment.name,
        questionnaire=questionnaire_hash(questionnaire),
        models=models,
        design=spec_design(experiment.design),
        analysis=experiment.analysis,
        preregistration=experiment.preregistration,
    )
    endpoints = model_endpoints(models, catalog)
    findings = (
        find_problems(questionnaire)
        + factor_findings(experiment.design.factors)
        + template_findings(experiment.design.prompt.template)
        + duplicate_model_findings(experiment.models)
        + missing_model_findings(experiment.models, catalog)
        + pinning_findings(endpoints)
        + elicitation_findings(models, endpoints)
        + preregistration_findings(path, experiment.preregistration, sources)
    )
    return CompiledExperiment(questionnaire=questionnaire, spec=spec, endpoints=endpoints, findings=findings)
