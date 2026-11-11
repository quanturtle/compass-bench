import pytest

from compass_bench.domain.design.experiment import design_prompt
from compass_bench.domain.design.factors import DisplayOrder, NumericMapping
from compass_bench.domain.elicitation.prompts import STANDARD_TEMPLATE, scale_legend, template_findings
from compass_bench.domain.instrument.scale import Scale
from tests.builders.design import BOTH_FACTORS, build_condition, build_design
from tests.builders.instrument import FIVE_POINT_LABELS

STATEMENT = "The state should fund public transport so that fares are low or free."
# the text every run has sent so far, which stored attempts hold and resume compares against
STANDARD_TEXT = (
    "Read the following statement and indicate how much you agree or disagree with it. "
    "Reply with a single number from the scale below and nothing else.\n\n"
    "Scale:\n1 = Strongly disagree\n2 = Disagree\n3 = Neither agree nor disagree\n4 = Agree\n5 = Strongly agree\n\n"
    f"Statement: {STATEMENT}"
)


def test_descending_agree_low_legend_lists_five_first_and_numbers_strongly_agree_one() -> None:
    condition = build_condition(DisplayOrder.DESCENDING, NumericMapping.AGREE_LOW)

    assert scale_legend(Scale(labels=FIVE_POINT_LABELS), condition) == (
        "5 = Strongly disagree",
        "4 = Disagree",
        "3 = Neither agree nor disagree",
        "2 = Agree",
        "1 = Strongly agree",
    )


def test_the_standard_prompt_renders_the_text_runs_have_been_sent() -> None:
    condition = build_condition(DisplayOrder.ASCENDING, NumericMapping.AGREE_HIGH)

    prompt = design_prompt(build_design(BOTH_FACTORS, 1), STATEMENT, condition, Scale(labels=FIVE_POINT_LABELS))

    assert [message.content for message in prompt.messages] == [STANDARD_TEXT]


def test_the_conditions_instruction_opens_the_prompt() -> None:
    instruction = "Express your view on the following statement."
    condition = build_condition(DisplayOrder.ASCENDING, NumericMapping.AGREE_HIGH, instruction)

    rendered = design_prompt(build_design(BOTH_FACTORS, 1), STATEMENT, condition, Scale(labels=FIVE_POINT_LABELS))

    assert rendered.messages[0].content.startswith(
        "Express your view on the following statement. Reply with a single number from the scale below"
    )


@pytest.mark.parametrize(
    ("template", "problems"),
    [
        (STANDARD_TEMPLATE, []),
        ("{instruction} {scale}", ["{statement} is missing"]),
        (STANDARD_TEMPLATE + " {topic}", ["{topic} is not a placeholder"]),
        (STANDARD_TEMPLATE + " {statement}", ["{statement} appears 2 times"]),
        (STANDARD_TEMPLATE.replace("{scale}", "{scale!r}"), ["{scale} carries a format or conversion"]),
        (STANDARD_TEMPLATE + " {", ["Single '{' encountered in format string"]),
    ],
    ids=["standard", "missing", "unknown", "repeated", "formatted", "unmatched brace"],
)
def test_a_template_must_name_each_placeholder_once_and_nothing_else(template: str, problems: list[str]) -> None:
    findings = template_findings(template)

    assert [finding.message for finding in findings] == [f"prompt template: {problem}" for problem in problems]
