"""Pre-flight checks and the plan summary, computed before anything is sent."""

import math
from collections.abc import Sequence

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity
from compass_bench.domain.budget import estimate_cost
from compass_bench.domain.claims import MIN_QUESTIONS
from compass_bench.domain.design.conditions import (
    Condition,
    display_order_levels,
    instruction_levels,
    numeric_mapping_levels,
)
from compass_bench.domain.design.experiment import (
    Design,
    ExperimentSpec,
    ModelSpec,
    design_conditions,
    design_prompt,
    effective_scale,
)
from compass_bench.domain.design.factors import FactorKind
from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import ConditionId
from compass_bench.domain.inference import position_level
from compass_bench.domain.instrument.questionnaire import Questionnaire, questions_on
from compass_bench.domain.instrument.scale import Scale, ScaleTooShort, points
from compass_bench.domain.stats.student_t import t_quantile
from compass_bench.domain.value import Value


class ConditionPrompt(Value):
    polarity: Polarity
    condition: ConditionId
    prompt: Prompt


class PlanSummary(Value):
    """`uniform_half_width` is the expected half-width of a position's interval for a responder that answers at
    random on the scale asked on, per axis; None on an axis with fewer than two questions."""

    spec: ExperimentSpec
    questionnaire: Questionnaire
    trial_count: int
    sample_prompts: tuple[ConditionPrompt, ...]
    estimated_cost_usd: float
    uniform_half_width: AxisPair[float | None]
    findings: tuple[Finding, ...]


def support_findings(spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """Warn when an axis has fewer questions than claims.MIN_QUESTIONS, the fewest a claim may rest on."""
    counts = {axis: len(questions_on(questionnaire, axis)) for axis in AxisKey}
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.BELOW_QUESTION_FLOOR,
            message=f"axis {axis} has {count} questions; a claim needs at least {MIN_QUESTIONS}",
        )
        for axis, count in counts.items()
        if count < MIN_QUESTIONS
    )


def variation_findings(spec: ExperimentSpec) -> tuple[Finding, ...]:
    """Warn when a factor kind has fewer than two levels, since the lean it counters then does not cancel."""
    leans = (
        (FactorKind.DISPLAY_ORDER, len(display_order_levels(spec.design.factors)), "toward the first-listed choice"),
        (FactorKind.NUMERIC_MAPPING, len(numeric_mapping_levels(spec.design.factors)), "toward high or low numbers"),
    )
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.UNVARIED_FACTOR,
            message=f"{kind} is not varied, so a model's lean {lean} does not cancel",
        )
        for kind, levels, lean in leans
        if levels < 2
    )


def wording_findings(spec: ExperimentSpec) -> tuple[Finding, ...]:
    """Warn when every question is asked in one wording, since a model's shift with the wording then stays in."""
    wordings = len(instruction_levels(spec.design.factors, spec.design.prompt.instruction))
    if wordings >= 2:
        return ()
    return (
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.SINGLE_WORDING,
            message="the questions are asked in one wording, so a model's shift with the wording does not average out",
        ),
    )


def scale_choice_findings(spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """An error when the design asks for forced choice on a scale too short to give four options."""
    try:
        effective_scale(spec.design, questionnaire.scale)
    except ScaleTooShort as error:
        return (Finding(severity=Severity.ERROR, code=FindingCode.SCALE_TOO_SHORT, message=str(error)),)
    return ()


def plan_findings(spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """Run every pre-flight check and return all findings."""
    return (
        support_findings(spec, questionnaire)
        + variation_findings(spec)
        + wording_findings(spec)
        + scale_choice_findings(spec, questionnaire)
    )


def trial_count(spec: ExperimentSpec, questionnaire: Questionnaire) -> int:
    phrasings = len(Polarity)
    conditions = len(design_conditions(spec.design))
    cells = len(spec.models) * len(questionnaire.questions) * phrasings * conditions
    return cells * spec.design.repetitions_per_condition


def sample_prompts(spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[ConditionPrompt, ...]:
    """The first question's two phrasings rendered under every condition; every answer type sends these prompts."""
    question = questionnaire.questions[0]
    scale = effective_scale(spec.design, questionnaire.scale)
    return tuple(
        ConditionPrompt(
            polarity=polarity,
            condition=condition.id,
            prompt=design_prompt(spec.design, question.statements.get(polarity), condition, scale),
        )
        for condition in design_conditions(spec.design)
        for polarity in Polarity
    )


def model_cost(
    model: ModelSpec,
    questionnaire: Questionnaire,
    scale: Scale,
    conditions: Sequence[Condition],
    design: Design,
) -> float:
    """One model's estimate for a single repetition: each question, phrasing, and condition asked once."""
    return sum(
        estimate_cost(
            design_prompt(design, question.statements.get(polarity), condition, scale),
            model.sampling.max_tokens,
            model.price,
        )
        for question in questionnaire.questions
        for polarity in Polarity
        for condition in conditions
    )


def estimated_cost(spec: ExperimentSpec, questionnaire: Questionnaire) -> float:
    """Estimate in USD: every trial asked once, with the full completion budget."""
    scale = effective_scale(spec.design, questionnaire.scale)
    conditions = design_conditions(spec.design)
    per_repetition = sum(
        model_cost(model, questionnaire, scale, conditions, spec.design) for model in spec.models.values()
    )
    return per_repetition * spec.design.repetitions_per_condition


def uniform_half_width(scale: Scale, cells: int, repetitions: int, questions: int, level: float) -> float | None:
    """The expected half-width of the position interval at `level` for answers uniform over the scale's points.

    A uniform rating on K points has answer-value variance (K + 1) / (3 (K − 1)); a question score averages
    2 × cells × repetitions of them, and the position averages `questions` scores. None below two questions."""
    if questions < 2:
        return None
    variance = (points(scale) + 1) / (3 * (points(scale) - 1))
    return t_quantile(level, questions - 1) * math.sqrt(variance / (2 * cells * repetitions * questions))


def uniform_half_widths(spec: ExperimentSpec, questionnaire: Questionnaire) -> AxisPair[float | None]:
    """Per axis, at the position interval's level, for the design's cells and repetitions."""
    scale = effective_scale(spec.design, questionnaire.scale)
    cells = len(design_conditions(spec.design))
    repetitions = spec.design.repetitions_per_condition
    level = position_level(spec.analysis)
    return AxisPair(
        x=uniform_half_width(scale, cells, repetitions, len(questions_on(questionnaire, AxisKey.X)), level),
        y=uniform_half_width(scale, cells, repetitions, len(questions_on(questionnaire, AxisKey.Y)), level),
    )


def summarize_plan(
    spec: ExperimentSpec, questionnaire: Questionnaire, compile_findings: Sequence[Finding]
) -> PlanSummary:
    """The findings are compile's structural ones followed by every pre-flight check's.

    Callers check those findings for errors first: an empty questionnaire or an unusable scale raises here."""
    return PlanSummary(
        spec=spec,
        questionnaire=questionnaire,
        trial_count=trial_count(spec, questionnaire),
        sample_prompts=sample_prompts(spec, questionnaire),
        estimated_cost_usd=estimated_cost(spec, questionnaire),
        uniform_half_width=uniform_half_widths(spec, questionnaire),
        findings=tuple(compile_findings) + plan_findings(spec, questionnaire),
    )
