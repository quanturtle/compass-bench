"""Conditions: one level per factor kind."""

from collections.abc import Sequence
from itertools import product
from typing import Final

from compass_bench.domain.design.factors import (
    DisplayOrder,
    DisplayOrderFactor,
    Factor,
    InstructionFactor,
    NumericMapping,
    NumericMappingFactor,
)
from compass_bench.domain.ids import ConditionId
from compass_bench.domain.value import Value

BASELINE_DISPLAY_ORDER: Final = DisplayOrder.ASCENDING
BASELINE_NUMERIC_MAPPING: Final = NumericMapping.AGREE_HIGH

# an instruction and the label its condition ids name it by; the design's own instruction has no label
type InstructionLevel = tuple[str | None, str]


class Condition(Value):
    """`id` equals condition_id of its levels; trials and their keys name the condition by it."""

    id: ConditionId
    display_order: DisplayOrder
    numeric_mapping: NumericMapping
    instruction: str


def condition_id(display_order: DisplayOrder, numeric_mapping: NumericMapping, label: str | None) -> ConditionId:
    """Readable, such as `ascending.agree_high`, or `ascending.agree_high.instruction-2` with an instruction label.

    An unvaried instruction has no label, so runs from before the instruction factor keep their trial keys."""
    levels = (display_order, numeric_mapping) if label is None else (display_order, numeric_mapping, label)
    return ConditionId(".".join(levels))


def display_order_levels(factors: Sequence[Factor]) -> tuple[DisplayOrder, ...]:
    """The first display-order factor's levels; factor_findings rejects a second one."""
    for factor in factors:
        if isinstance(factor, DisplayOrderFactor):
            return factor.levels
    return (BASELINE_DISPLAY_ORDER,)


def numeric_mapping_levels(factors: Sequence[Factor]) -> tuple[NumericMapping, ...]:
    """The first numeric-mapping factor's levels; factor_findings rejects a second one."""
    for factor in factors:
        if isinstance(factor, NumericMappingFactor):
            return factor.levels
    return (BASELINE_NUMERIC_MAPPING,)


def instruction_levels(factors: Sequence[Factor], baseline: str) -> tuple[InstructionLevel, ...]:
    """The first instruction factor's levels, labelled `instruction-1` onward, or the baseline without a label."""
    for factor in factors:
        if isinstance(factor, InstructionFactor):
            return tuple((f"instruction-{number}", text) for number, text in enumerate(factor.levels, start=1))
    return ((None, baseline),)


def cross(factors: Sequence[Factor], baseline_instruction: str) -> tuple[Condition, ...]:
    """Full crossing of the factor levels; a factor kind not listed stays at its baseline level.

    The instruction's baseline is the design's prompt.instruction."""
    return tuple(
        Condition(
            id=condition_id(order, mapping, label),
            display_order=order,
            numeric_mapping=mapping,
            instruction=instruction,
        )
        for order, mapping, (label, instruction) in product(
            display_order_levels(factors),
            numeric_mapping_levels(factors),
            instruction_levels(factors, baseline_instruction),
        )
    )
