from compass_bench.domain.design.conditions import BASELINE_DISPLAY_ORDER, BASELINE_NUMERIC_MAPPING, cross
from compass_bench.domain.design.factors import (
    DisplayOrder,
    DisplayOrderFactor,
    FactorKind,
    InstructionFactor,
    NumericMapping,
    NumericMappingFactor,
)
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION
from tests.builders.design import BOTH_FACTORS


def test_cross_of_both_factors_gives_four_distinct_conditions() -> None:
    conditions = cross(
        (
            DisplayOrderFactor(kind=FactorKind.DISPLAY_ORDER, levels=tuple(DisplayOrder)),
            NumericMappingFactor(kind=FactorKind.NUMERIC_MAPPING, levels=tuple(NumericMapping)),
        ),
        STANDARD_INSTRUCTION,
    )

    assert len({condition.id for condition in conditions}) == 4


def test_cross_of_no_factors_is_the_baseline_with_the_designs_instruction_and_no_instruction_label() -> None:
    (condition,) = cross((), "Express your view on the following statement.")

    assert (condition.id, condition.display_order, condition.numeric_mapping, condition.instruction) == (
        "ascending.agree_high",
        BASELINE_DISPLAY_ORDER,
        BASELINE_NUMERIC_MAPPING,
        "Express your view on the following statement.",
    )


def test_an_instruction_factor_crosses_each_instruction_and_labels_it_in_the_condition_id() -> None:
    wordings = ("Express your view on the following statement.", "Give me your opinion on the following statement.")
    factors = (*BOTH_FACTORS, InstructionFactor(kind=FactorKind.INSTRUCTION, levels=wordings))

    conditions = cross(factors, STANDARD_INSTRUCTION)

    assert [(condition.id, condition.instruction) for condition in conditions[:2]] == [
        ("ascending.agree_high.instruction-1", wordings[0]),
        ("ascending.agree_high.instruction-2", wordings[1]),
    ]
    assert len({condition.id for condition in conditions}) == 8
