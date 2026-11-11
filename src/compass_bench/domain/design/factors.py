"""Presentation factors.

A new factor kind adds a variant here, a Condition field with a baseline level, and a rendering effect.
"""

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.instrument.scale import CanonicalRating, DisplayedRating, Scale, points
from compass_bench.domain.value import Value


class FactorKind(StrEnum):
    DISPLAY_ORDER = "display_order"
    NUMERIC_MAPPING = "numeric_mapping"
    INSTRUCTION = "instruction"


class DisplayOrder(StrEnum):
    """The order the scale lines are listed in."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


class NumericMapping(StrEnum):
    """Which end of the scale the highest number means."""

    AGREE_HIGH = "agree_high"
    AGREE_LOW = "agree_low"


class DisplayOrderFactor(Value):
    kind: Literal[FactorKind.DISPLAY_ORDER]
    levels: tuple[DisplayOrder, ...]


class NumericMappingFactor(Value):
    kind: Literal[FactorKind.NUMERIC_MAPPING]
    levels: tuple[NumericMapping, ...]


class InstructionFactor(Value):
    """Each level is an instruction that fills the prompt template's {instruction}."""

    kind: Literal[FactorKind.INSTRUCTION]
    levels: tuple[Annotated[str, Field(min_length=1)], ...]


type Factor = Annotated[DisplayOrderFactor | NumericMappingFactor | InstructionFactor, Field(discriminator="kind")]


def displayed_rating(scale: Scale, mapping: NumericMapping, rating: CanonicalRating) -> DisplayedRating:
    """Ratings run from 1 to K; agree_low shows canonical r as K + 1 - r."""
    match mapping:
        case NumericMapping.AGREE_HIGH:
            return DisplayedRating(rating)
        case NumericMapping.AGREE_LOW:
            return DisplayedRating(points(scale) + 1 - rating)


def canonical_rating(scale: Scale, mapping: NumericMapping, displayed: DisplayedRating) -> CanonicalRating:
    """Invert displayed_rating; every reading is converted with this before scoring."""
    match mapping:
        case NumericMapping.AGREE_HIGH:
            return CanonicalRating(displayed)
        case NumericMapping.AGREE_LOW:
            return CanonicalRating(points(scale) + 1 - displayed)


def enum_position(member: StrEnum) -> int:
    return list(type(member)).index(member)


def canonical_levels(factor: Factor) -> Factor:
    """The factor with its levels in enum order, or instructions in text order; a repeated level stays repeated."""
    match factor:
        case DisplayOrderFactor():
            return DisplayOrderFactor(kind=factor.kind, levels=tuple(sorted(factor.levels, key=enum_position)))
        case NumericMappingFactor():
            return NumericMappingFactor(kind=factor.kind, levels=tuple(sorted(factor.levels, key=enum_position)))
        case InstructionFactor():
            return InstructionFactor(kind=factor.kind, levels=tuple(sorted(factor.levels)))


def canonical_factors(factors: Sequence[Factor]) -> tuple[Factor, ...]:
    """Factors in FactorKind order, each with its levels in enum order, so the authored order changes no hash."""
    return tuple(
        sorted((canonical_levels(factor) for factor in factors), key=lambda factor: enum_position(factor.kind))
    )


def level_findings(factors: Sequence[Factor]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for factor in factors:
        if not factor.levels:
            message = f"{factor.kind} lists no levels"
            findings.append(Finding(severity=Severity.ERROR, code=FindingCode.EMPTY_FACTOR, message=message))
        counts = Counter[str](factor.levels)
        findings.extend(
            Finding(
                severity=Severity.ERROR,
                code=FindingCode.DUPLICATE_LEVEL,
                message=f"{factor.kind} lists {level} {count} times",
            )
            for level, count in counts.items()
            if count > 1
        )
    return tuple(findings)


def duplicate_factor_findings(factors: Sequence[Factor]) -> tuple[Finding, ...]:
    counts = Counter(factor.kind for factor in factors)
    return tuple(
        Finding(severity=Severity.ERROR, code=FindingCode.DUPLICATE_FACTOR, message=f"{kind} is listed {count} times")
        for kind, count in counts.items()
        if count > 1
    )


def factor_findings(factors: Sequence[Factor]) -> tuple[Finding, ...]:
    """Errors for a factor with no levels or a repeated level, and for two factors of one kind."""
    return level_findings(factors) + duplicate_factor_findings(factors)
