"""Conditions and experiment specs."""

from collections.abc import Mapping
from typing import Final

from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.budget import Price
from compass_bench.domain.design.conditions import (
    BASELINE_DISPLAY_ORDER,
    BASELINE_NUMERIC_MAPPING,
    Condition,
    condition_id,
)
from compass_bench.domain.design.experiment import (
    AnalysisSettings,
    AnswerType,
    Design,
    ExperimentSpec,
    ModelSpec,
    ReasoningEffort,
    Sampling,
    ScaleChoice,
)
from compass_bench.domain.design.factors import (
    DisplayOrder,
    DisplayOrderFactor,
    Factor,
    FactorKind,
    NumericMapping,
    NumericMappingFactor,
)
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION, STANDARD_PROMPT
from compass_bench.domain.ids import EndpointId, ModelId, QuestionId, TrialKey
from compass_bench.domain.instrument.questionnaire import Questionnaire, questionnaire_hash

BOTH_FACTORS: Final[tuple[Factor, ...]] = (
    DisplayOrderFactor(kind=FactorKind.DISPLAY_ORDER, levels=tuple(DisplayOrder)),
    NumericMappingFactor(kind=FactorKind.NUMERIC_MAPPING, levels=tuple(NumericMapping)),
)


def build_trial(key: str, model: str, position: int) -> Trial:
    """A trial of question `x-00`'s positive phrasing under the baseline condition."""
    return Trial(
        key=TrialKey(key),
        model=ModelId(model),
        question=QuestionId("x-00"),
        polarity=Polarity.POSITIVE,
        condition=condition_id(BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING, None),
        repetition=0,
        position=position,
    )


def build_condition(
    display_order: DisplayOrder, numeric_mapping: NumericMapping, instruction: str = STANDARD_INSTRUCTION
) -> Condition:
    """A condition of a design that does not vary the instruction, so its id has no instruction label."""
    return Condition(
        id=condition_id(display_order, numeric_mapping, None),
        display_order=display_order,
        numeric_mapping=numeric_mapping,
        instruction=instruction,
    )


def build_model_spec(answer_type: AnswerType) -> ModelSpec:
    return ModelSpec(
        endpoint=EndpointId("openrouter"),
        model="vendor/model",
        sampling=Sampling(temperature=0.0, top_p=None, max_tokens=8, reasoning=ReasoningEffort.OFF),
        answer_type=answer_type,
        price=Price(prompt_usd_per_million=1.0, completion_usd_per_million=5.0),
    )


def build_design(factors: tuple[Factor, ...], repetitions: int) -> Design:
    return Design(
        factors=factors,
        repetitions_per_condition=repetitions,
        scale=ScaleChoice.NATIVE,
        system_prompt=None,
        prompt=STANDARD_PROMPT,
        max_retries=3,
    )


def build_spec(questionnaire: Questionnaire, models: Mapping[ModelId, ModelSpec], design: Design) -> ExperimentSpec:
    return ExperimentSpec(
        name="test experiment",
        questionnaire=questionnaire_hash(questionnaire),
        models=models,
        design=design,
        analysis=AnalysisSettings(confidence_level=0.95, coverage_floor=0.8, equivalence_margin=0.1),
        preregistration=None,
    )
