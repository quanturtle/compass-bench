"""What a reply says, and which rule decided it. Readings are on the canonical scale."""

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Annotated, Final, Literal, NewType

from pydantic import Field

from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.factors import canonical_rating
from compass_bench.domain.instrument.scale import CanonicalRating, DisplayedRating, Scale, points
from compass_bench.domain.ledger import Reply
from compass_bench.domain.value import Value

RuleId = NewType("RuleId", str)
NO_DECISION: Final = RuleId("no_decision")


class FormatFailureKind(StrEnum):
    EMPTY = "empty"
    NO_DIGIT = "no_digit"
    AMBIGUOUS = "ambiguous"
    OUT_OF_RANGE = "out_of_range"
    TRUNCATED = "truncated"
    SCHEMA_INVALID = "schema_invalid"


class Span(Value):
    start: int
    end: int


class ReadingKind(StrEnum):
    RATING = "rating"
    DECLINE = "decline"
    FORMAT_FAILURE = "format_failure"


class RatingRead(Value):
    """A rating read from a reply; `hedge` is where decline wording stood beside the number, or None."""

    kind: Literal[ReadingKind.RATING]
    canonical: CanonicalRating
    displayed: DisplayedRating
    span: Span
    rule: RuleId
    hedge: Span | None


class DeclineRead(Value):
    kind: Literal[ReadingKind.DECLINE]
    evidence: Span
    rule: RuleId


class FormatFailure(Value):
    kind: Literal[ReadingKind.FORMAT_FAILURE]
    failure: FormatFailureKind
    rule: RuleId


type Reading = Annotated[RatingRead | DeclineRead | FormatFailure, Field(discriminator="kind")]


class ReadContext(Value):
    scale: Scale
    condition: Condition


ReadRule = Callable[[Reply, ReadContext], Reading | None]


def rating_reading(
    displayed: int, span: Span, rule: RuleId, context: ReadContext, hedge: Span | None
) -> RatingRead | FormatFailure:
    """The displayed rating on the canonical scale, or OUT_OF_RANGE when the scale does not show it.

    `hedge` is decided by the rule as it reads, never filled in later."""
    if not 1 <= displayed <= points(context.scale):
        return FormatFailure(kind=ReadingKind.FORMAT_FAILURE, failure=FormatFailureKind.OUT_OF_RANGE, rule=rule)
    shown = DisplayedRating(displayed)
    return RatingRead(
        kind=ReadingKind.RATING,
        canonical=canonical_rating(context.scale, context.condition.numeric_mapping, shown),
        displayed=shown,
        span=span,
        rule=rule,
        hedge=hedge,
    )


def first_decision(rules: Sequence[ReadRule], reply: Reply, context: ReadContext) -> Reading:
    """Apply rules in order (Chain of Responsibility); no decision is an AMBIGUOUS failure under NO_DECISION."""
    for rule in rules:
        reading = rule(reply, context)
        if reading is not None:
            return reading
    return FormatFailure(kind=ReadingKind.FORMAT_FAILURE, failure=FormatFailureKind.AMBIGUOUS, rule=NO_DECISION)
