import pytest

from compass_bench.adapters.terminal.plan_view import design_lines
from compass_bench.domain.design.factors import Factor, FactorKind, InstructionFactor
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from tests.builders.design import BOTH_FACTORS, build_design

WORDINGS = (STANDARD_INSTRUCTION, "Express your view on the following statement.")


@pytest.mark.parametrize(
    ("factors", "note"),
    [
        (BOTH_FACTORS, ""),
        (
            (*BOTH_FACTORS, InstructionFactor(kind=FactorKind.INSTRUCTION, levels=WORDINGS)),
            " (not sent: the instruction factor's levels replace it)",
        ),
    ],
    ids=["no instruction factor", "instruction factor"],
)
def test_the_plan_marks_prompt_instruction_as_not_sent_under_an_instruction_factor(
    factors: tuple[Factor, ...], note: str
) -> None:
    lines = design_lines(build_design(factors, 1))

    assert f'prompt.instruction: "{STANDARD_INSTRUCTION}"{note}' in lines
