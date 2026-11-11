"""Text for `plan`."""

import json
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import JsonValue

from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import (
    Design,
    design_conditions,
    effective_scale,
    experiment_hash,
    sends_prompt_instruction,
)
from compass_bench.domain.design.preflight import ConditionPrompt, PlanSummary
from compass_bench.domain.findings import Finding, Severity
from compass_bench.domain.ids import EndpointId
from compass_bench.domain.instrument.compass import Compass
from compass_bench.domain.instrument.questionnaire import Questionnaire, questions_on

INDENT: Final = "  "
PROMPT_INSTRUCTION: Final = "prompt.instruction: "
UNSENT_INSTRUCTION: Final = " (not sent: the instruction factor's levels replace it)"


def render_findings(findings: Sequence[Finding]) -> str:
    """Errors first, then warnings, each with its code."""
    return "\n".join(
        f"{finding.severity}: {finding.code}: {finding.message}"
        for severity in Severity
        for finding in findings
        if finding.severity is severity
    )


def indented(line: str) -> str:
    """A blank line stays blank, so no line ends in whitespace."""
    return f"{INDENT}{line}" if line else ""


def section(title: str, lines: Sequence[str]) -> str:
    return "\n".join([title, *(indented(line) for line in lines)])


def value_lines(document: Mapping[str, JsonValue], prefix: str) -> tuple[str, ...]:
    """One `key: value` line per leaf, values as JSON; nested keys join with dots after `prefix`."""
    lines: list[str] = []
    for key, value in document.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            lines.extend(value_lines(value, f"{name}."))
        else:
            lines.append(f"{name}: {json.dumps(value)}")
    return tuple(lines)


def experiment_section(summary: PlanSummary) -> str:
    return section(
        "Experiment",
        (
            f"name: {summary.spec.name}",
            f"experiment hash: {experiment_hash(summary.spec)}",
            f"questionnaire hash: {summary.spec.questionnaire}",
        ),
    )


def axis_line(questionnaire: Questionnaire, axis: AxisKey) -> str:
    named = questionnaire.compass.axes.get(axis)
    poles = f"negative pole: {named.negative}, positive pole: {named.positive}"
    return f"axis {axis}: {named.name} ({poles}), {len(questions_on(questionnaire, axis))} questions"


def questionnaire_section(summary: PlanSummary) -> str:
    questionnaire = summary.questionnaire
    asked = effective_scale(summary.spec.design, questionnaire.scale)
    return section(
        "Questionnaire",
        (
            f"title: {questionnaire.title}",
            f"author: {questionnaire.author}",
            *(axis_line(questionnaire, axis) for axis in AxisKey),
            f"scale: {' | '.join(questionnaire.scale.labels)}",
            f"asked on: {' | '.join(asked.labels)}",
        ),
    )


def design_lines(design: Design) -> tuple[str, ...]:
    """The design's values, with prompt.instruction marked when an instruction factor replaces it."""
    lines = value_lines(design.model_dump(mode="json"), "")
    if sends_prompt_instruction(design):
        return lines
    return tuple(f"{line}{UNSENT_INSTRUCTION}" if line.startswith(PROMPT_INSTRUCTION) else line for line in lines)


def design_section(summary: PlanSummary) -> str:
    conditions = ", ".join(condition.id for condition in design_conditions(summary.spec.design))
    return section("Design", (*design_lines(summary.spec.design), f"conditions: {conditions}"))


def model_sections(summary: PlanSummary) -> tuple[str, ...]:
    return tuple(
        section(f"Model {name}", value_lines(model.model_dump(mode="json"), ""))
        for name, model in summary.spec.models.items()
    )


def endpoint_sections(endpoints: Mapping[EndpointId, EndpointSettings]) -> tuple[str, ...]:
    """Settings name the API key's variable, never the key."""
    return tuple(
        section(f"Endpoint {name}", value_lines(settings.model_dump(mode="json"), ""))
        for name, settings in endpoints.items()
    )


def labelled_lines(label: str, text: str) -> tuple[str, ...]:
    """The text's first line after `[label]`, and every later line indented beneath it."""
    return tuple(f"[{label}] {line}" if index == 0 else indented(line) for index, line in enumerate(text.splitlines()))


def prompt_section(sample: ConditionPrompt, compass: Compass, axis: AxisKey) -> str:
    pole = compass.axes.get(axis).pole(sample.polarity)
    system = () if sample.prompt.system is None else labelled_lines("system", sample.prompt.system)
    messages = tuple(
        line for message in sample.prompt.messages for line in labelled_lines(message.role, message.content)
    )
    return section(f"Prompt (condition: {sample.condition}, phrasing toward {pole})", (*system, *messages))


def prompt_sections(summary: PlanSummary) -> tuple[str, ...]:
    """Every sample is the first question's, so they share its axis."""
    axis = summary.questionnaire.questions[0].axis
    return tuple(prompt_section(sample, summary.questionnaire.compass, axis) for sample in summary.sample_prompts)


def half_width_text(half_width: float | None) -> str:
    return "undefined" if half_width is None else f"{half_width:.3f}"


def totals_section(summary: PlanSummary) -> str:
    warnings = render_findings(summary.findings).splitlines() or ["none"]
    return section(
        "Totals",
        (
            f"trials: {summary.trial_count}",
            f"estimated cost: ${summary.estimated_cost_usd:.4f} (every trial asked once at full max_tokens; "
            "prompt tokens estimated at 3 characters each, reply schema not counted)",
            f"a responder answering at random would show 0 ± {half_width_text(summary.uniform_half_width.x)} on x "
            f"and 0 ± {half_width_text(summary.uniform_half_width.y)} on y at the position interval's level",
            "warnings:",
            *(indented(warning) for warning in warnings),
        ),
    )


def render_plan(summary: PlanSummary, endpoints: Mapping[EndpointId, EndpointSettings]) -> str:
    """Every resolved value, endpoint settings included, the sample prompts, the trial count, and the cost estimate."""
    sections = (
        experiment_section(summary),
        questionnaire_section(summary),
        design_section(summary),
        section("Analysis", value_lines(summary.spec.analysis.model_dump(mode="json"), "")),
        *model_sections(summary),
        *endpoint_sections(endpoints),
        *prompt_sections(summary),
        totals_section(summary),
    )
    return "\n\n".join(sections)
