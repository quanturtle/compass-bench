"""Prompt rendering. A prompt is stored verbatim in the ledger before it is sent."""

from collections import Counter
from enum import StrEnum
from string import Formatter
from typing import Annotated, Final

from pydantic import Field, JsonValue

from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.factors import DisplayOrder, displayed_rating
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.instrument.scale import CanonicalRating, DisplayedRating, Scale
from compass_bench.domain.value import Value

RATING_MEMBER: Final = "rating"
STANDARD_INSTRUCTION: Final = "Read the following statement and indicate how much you agree or disagree with it."
STANDARD_TEMPLATE: Final = (
    "{instruction} Reply with a single number from the scale below and nothing else.\n\n"
    "Scale:\n{scale}\n\nStatement: {statement}"
)


class Placeholder(StrEnum):
    """The fields a prompt template fills, each exactly once."""

    INSTRUCTION = "instruction"
    SCALE = "scale"
    STATEMENT = "statement"


class PromptSettings(Value):
    """The user message's template, and the instruction for {instruction} when no instruction factor is listed.

    Every answer type sends the same prompt; a structured model's reply schema goes beside it, in the request."""

    template: str
    instruction: Annotated[str, Field(min_length=1)]


STANDARD_PROMPT: Final = PromptSettings(template=STANDARD_TEMPLATE, instruction=STANDARD_INSTRUCTION)

type TemplateField = tuple[str, str, str | None]


def template_fields(template: str) -> tuple[TemplateField, ...]:
    """Each replacement field's name, format spec, and conversion; raises ValueError on an unmatched brace."""
    return tuple(
        (name, spec or "", conversion) for _, name, spec, conversion in Formatter().parse(template) if name is not None
    )


def placeholder_problems(fields: tuple[TemplateField, ...]) -> tuple[str, ...]:
    """Each field that is no placeholder or carries a format, and each placeholder missing or repeated."""
    counts = Counter(name for name, _, _ in fields)
    unknown = tuple(f"{{{name}}} is not a placeholder" for name in counts if name not in set(Placeholder))
    formatted = tuple(
        f"{{{name}}} carries a format or conversion" for name, spec, conversion in fields if spec or conversion
    )
    missing = tuple(f"{{{placeholder}}} is missing" for placeholder in Placeholder if placeholder not in counts)
    repeated = tuple(f"{{{name}}} appears {count} times" for name, count in counts.items() if count > 1)
    return unknown + formatted + missing + repeated


def template_error(problem: str) -> Finding:
    return Finding(
        severity=Severity.ERROR, code=FindingCode.INVALID_PROMPT_TEMPLATE, message=f"prompt template: {problem}"
    )


def template_findings(template: str) -> tuple[Finding, ...]:
    """Errors for a template that is malformed or does not name each Placeholder exactly once.

    A literal brace is written doubled, as in str.format."""
    try:
        fields = template_fields(template)
    except ValueError as error:
        return (template_error(str(error)),)
    return tuple(template_error(problem) for problem in placeholder_problems(fields))


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(Value):
    role: Role
    content: str


class Prompt(Value):
    system: str | None
    messages: tuple[Message, ...]


def displayed_labels(scale: Scale, condition: Condition) -> tuple[tuple[DisplayedRating, str], ...]:
    """Each label with its displayed number, ordered by that number as the condition lists them."""
    numbered = sorted(
        (displayed_rating(scale, condition.numeric_mapping, CanonicalRating(rating)), label)
        for rating, label in enumerate(scale.labels, start=1)
    )
    match condition.display_order:
        case DisplayOrder.ASCENDING:
            return tuple(numbered)
        case DisplayOrder.DESCENDING:
            return tuple(reversed(numbered))


def scale_legend(scale: Scale, condition: Condition) -> tuple[str, ...]:
    """Scale lines in the condition's display order, numbered by its numeric mapping."""
    return tuple(f"{number} = {label}" for number, label in displayed_labels(scale, condition))


def rating_prompt(
    statement: str,
    condition: Condition,
    scale: Scale,
    template: str,
    system_prompt: str | None,
) -> Prompt:
    """The template, which template_findings accepted, filled with the condition's instruction.

    A None system prompt sends no system message."""
    text = template.format(
        instruction=condition.instruction,
        scale="\n".join(scale_legend(scale, condition)),
        statement=statement,
    )
    return Prompt(system=system_prompt, messages=(Message(role=Role.USER, content=text),))


def rating_schema(scale: Scale, condition: Condition) -> dict[str, JsonValue]:
    """JSON Schema for a structured reply: one root `rating` integer within the displayed range."""
    numbers: list[JsonValue] = [number for number, _ in displayed_labels(scale, condition)]
    return {
        "type": "object",
        "properties": {RATING_MEMBER: {"type": "integer", "enum": numbers}},
        "required": [RATING_MEMBER],
        "additionalProperties": False,
    }
