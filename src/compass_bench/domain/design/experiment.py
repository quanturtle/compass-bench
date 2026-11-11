"""The experiment specification. Fields that change the experiment have no defaults."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt

from compass_bench.domain.budget import Price
from compass_bench.domain.design.conditions import Condition, cross
from compass_bench.domain.design.factors import Factor, FactorKind, canonical_factors
from compass_bench.domain.elicitation.prompts import Prompt, PromptSettings, rating_prompt
from compass_bench.domain.ids import EndpointId, ExperimentHash, ModelId, QuestionnaireHash, content_hash
from compass_bench.domain.instrument.scale import Scale, forced_choice
from compass_bench.domain.value import Value


class ReasoningEffort(StrEnum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnswerType(StrEnum):
    """How a model is asked to answer: a bare number, or a JSON object a reply schema constrains."""

    FREE_TEXT = "free_text"
    STRUCTURED = "structured"


class ScaleChoice(StrEnum):
    NATIVE = "native"
    FORCED_CHOICE = "forced_choice"


class Sampling(Value):
    """No sampling seed: one fixed seed would let a provider return the same reply for every repetition."""

    temperature: NonNegativeFloat
    top_p: Annotated[float, Field(gt=0, le=1)] | None
    max_tokens: PositiveInt
    reasoning: ReasoningEffort


class ModelSpec(Value):
    """What to ask a model with; how to reach its endpoint is transport configuration.

    It carries no id: every mapping that holds it is keyed by ModelId."""

    endpoint: EndpointId
    model: str
    sampling: Sampling
    answer_type: AnswerType
    price: Price


class Design(Value):
    """Each factor lists its levels; design_conditions gives the conditions, and a kind not listed stays at baseline.

    A system prompt is absent or not empty, since an empty one is still sent as a system message."""

    factors: tuple[Factor, ...]
    repetitions_per_condition: PositiveInt
    scale: ScaleChoice
    system_prompt: Annotated[str, Field(min_length=1)] | None
    prompt: PromptSettings
    max_retries: NonNegativeInt


class AnalysisSettings(Value):
    """`coverage_floor` is the smallest share of a model's trials on an axis that must be answered for a claim.

    `equivalence_margin` is the largest gap, in score units, that still counts as no difference between two models."""

    confidence_level: Annotated[float, Field(gt=0, lt=1)]
    coverage_floor: Annotated[float, Field(ge=0, le=1)]
    equivalence_margin: Annotated[float, Field(gt=0, lt=2)]


class ExperimentSpec(Value):
    """`preregistration` is the path of the filled preregistration committed before the run, relative to the
    experiment file, or None; a report is confirmatory only when the stored spec names one."""

    name: str
    questionnaire: QuestionnaireHash
    models: Mapping[ModelId, ModelSpec]
    design: Design
    analysis: AnalysisSettings
    preregistration: str | None


def canonical_design(design: Design) -> Design:
    """The design with canonical_factors, so two authorings of one design give one experiment hash."""
    return Design.model_validate({**dict(design), "factors": canonical_factors(design.factors)})


def design_conditions(design: Design) -> tuple[Condition, ...]:
    """cross of the design's factors; without an instruction factor, every condition asks prompt.instruction."""
    return cross(design.factors, design.prompt.instruction)


def design_prompt(design: Design, statement: str, condition: Condition, scale: Scale) -> Prompt:
    """The prompt the design asks `statement` with under `condition`; it is the same for every answer type."""
    return rating_prompt(statement, condition, scale, design.prompt.template, design.system_prompt)


def sends_prompt_instruction(design: Design) -> bool:
    """False when an instruction factor is listed, since its levels replace prompt.instruction."""
    return all(factor.kind is not FactorKind.INSTRUCTION for factor in design.factors)


def experiment_hash(spec: ExperimentSpec) -> ExperimentHash:
    return ExperimentHash(content_hash(spec.model_dump(mode="json")))


def effective_scale(design: Design, scale: Scale) -> Scale:
    """The scale the design asks on: the questionnaire's own, or its forced-choice form."""
    match design.scale:
        case ScaleChoice.NATIVE:
            return scale
        case ScaleChoice.FORCED_CHOICE:
            return forced_choice(scale)


def significance_level(settings: AnalysisSettings) -> float:
    """Alpha for pair claims: 1 - confidence_level."""
    return 1 - settings.confidence_level
