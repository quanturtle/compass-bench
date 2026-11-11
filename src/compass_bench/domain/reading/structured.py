"""Structured-reply rules: the standard JSON parser and the root `rating` member, nothing else."""

import json
import re
from typing import Final

from compass_bench.domain.elicitation.prompts import RATING_MEMBER
from compass_bench.domain.ledger import Reply
from compass_bench.domain.reading.free_text import blank_reply, format_failure, truncated_reply
from compass_bench.domain.reading.reading import (
    FormatFailureKind,
    ReadContext,
    Reading,
    ReadRule,
    RuleId,
    Span,
    rating_reading,
)

# where an integer rating member is written; the span is evidence, so a nested match of equal value is harmless
RATING_MEMBER_PATTERN: Final = re.compile(rf'"{RATING_MEMBER}"\s*:\s*(-?[0-9]+)')


def invalid_json(reply: Reply, context: ReadContext) -> Reading | None:
    try:
        json.loads(reply.text)
    except ValueError, RecursionError:
        return format_failure(FormatFailureKind.SCHEMA_INVALID, RuleId("invalid_json"))
    return None


class RepeatedMember(Exception):
    """A JSON object names one member twice."""


def reject_repeated_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """object_pairs_hook for json.loads: raise RepeatedMember instead of keeping the last value."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise RepeatedMember
    return dict(pairs)


def repeated_member(reply: Reply, context: ReadContext) -> Reading | None:
    """An object that names a member twice, such as two `rating` members; the standard parser keeps the last one."""
    try:
        json.loads(reply.text, object_pairs_hook=reject_repeated_members)
    except RepeatedMember:
        return format_failure(FormatFailureKind.SCHEMA_INVALID, RuleId("repeated_member"))
    return None


def missing_rating(reply: Reply, context: ReadContext) -> Reading | None:
    """A root that is not an object, or has no `rating` member; runs after invalid_json."""
    document = json.loads(reply.text)
    if not isinstance(document, dict) or RATING_MEMBER not in document:
        return format_failure(FormatFailureKind.SCHEMA_INVALID, RuleId("missing_rating"))
    return None


def rating_span(text: str, rating: int) -> Span:
    """Where the member's digits are written, or the whole reply when the key is spelled with escapes."""
    matches = [match for match in RATING_MEMBER_PATTERN.finditer(text) if int(match.group(1)) == rating]
    if not matches:
        return Span(start=0, end=len(text))
    return Span(start=matches[-1].start(1), end=matches[-1].end(1))


def rating_member(reply: Reply, context: ReadContext) -> Reading | None:
    """Read the root `rating` integer; a value off the displayed scale is OUT_OF_RANGE."""
    rule = RuleId("rating_member")
    rating = json.loads(reply.text)[RATING_MEMBER]
    if isinstance(rating, bool) or not isinstance(rating, int):
        return format_failure(FormatFailureKind.SCHEMA_INVALID, rule)
    return rating_reading(rating, rating_span(reply.text, rating), rule, context, None)


STRUCTURED_RULES: Final[tuple[ReadRule, ...]] = (
    truncated_reply,
    blank_reply,
    invalid_json,
    repeated_member,
    missing_rating,
    rating_member,
)
