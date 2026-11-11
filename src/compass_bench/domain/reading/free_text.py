"""Free-text rules, in decision order. A regression becomes a corpus row, not a new branch."""

import re
from typing import Final

from compass_bench.domain.ledger import FinishReason, Reply
from compass_bench.domain.reading.reading import (
    DeclineRead,
    FormatFailure,
    FormatFailureKind,
    ReadContext,
    Reading,
    ReadingKind,
    ReadRule,
    RuleId,
    Span,
    rating_reading,
)

# a whole number token, so a decimal or an exponent never yields a fragment that reads as a rating
NUMBER: Final = r"[-+]?(?:[0-9]{1,9}(?:\.[0-9]{1,9})?|\.[0-9]{1,9})(?:[eE][-+]?[0-9]{1,9})?"
INTEGER_PATTERN: Final = re.compile(r"[-+]?[0-9]{1,9}")
OVERSIZED_NUMBER_PATTERN: Final = re.compile(r"[0-9]{10}")
BARE_NUMBER_PATTERN: Final = re.compile(rf"^[\s\W]*?({NUMBER})[\s\W]*$")
NON_EMPTY_LINE_PATTERN: Final = re.compile(r"[^\r\n]*\S[^\r\n]*")

# the lookbehind keeps "1-5" reading as 1 and 5, not 1 and -5
NUMBER_TOKEN_PATTERN: Final = re.compile(rf"(?<![0-9]){NUMBER}")
ANCHORED_RATING_PATTERN: Final = re.compile(rf"(?:answer|rating)\s*(?:is\b|:|=)?\s*({NUMBER})", re.IGNORECASE)

# agree and disagree are the scale's own words, so "I cannot agree more" takes a position
NOT_ABOUT_AGREEING: Final = r"(?!\s+(?:\w+\s+)?(?:agree|disagree)\b)"
# models write the typographic apostrophe as often as the ASCII one
APOSTROPHE: Final = "['’]"
DECLINE_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"\bi\s+(?:can\s*not|can{APOSTROPHE}t|won{APOSTROPHE}t|will\s+not|must\s+(?:decline|refrain|abstain)"
        rf"|refuse|decline)\b" + NOT_ABOUT_AGREEING,
        rf"\bi(?:{APOSTROPHE}m| am)\s+(?:not\s+able|unable)\s+to\b" + NOT_ABOUT_AGREEING,
        rf"\bi(?:{APOSTROPHE}d| would)\s+rather\s+not\b",
        rf"\bi(?:{APOSTROPHE}d| would)?\s+(?:prefer|choose)\s+not\s+to\b",
        r"\bno\s+comment\b",
        rf"\bi\s+(?:do\s+not|don{APOSTROPHE}t)\s+(?:have|hold|express)\s+(?:an?\s+)?(?:personal\s+)?"
        r"(?:opinions?|beliefs?|views?|stances?|positions?)\b",
        rf"\bi\s+(?:do\s+not|don{APOSTROPHE}t)\s+feel\s+comfortable\b",
    )
)


def format_failure(failure: FormatFailureKind, rule: RuleId) -> FormatFailure:
    return FormatFailure(kind=ReadingKind.FORMAT_FAILURE, failure=failure, rule=rule)


def truncated_decline(reply: Reply, context: ReadContext) -> Reading | None:
    """A reply cut off at max_tokens with decline wording and no number declined.

    One cut off after a number stays truncated, since the cut may have removed the commitment."""
    if reply.finish is not FinishReason.LENGTH or NUMBER_TOKEN_PATTERN.search(reply.text) is not None:
        return None
    evidence = decline_evidence(reply.text)
    if evidence is None:
        return None
    return DeclineRead(kind=ReadingKind.DECLINE, evidence=evidence, rule=RuleId("truncated_decline"))


def truncated_reply(reply: Reply, context: ReadContext) -> Reading | None:
    if reply.finish is FinishReason.LENGTH:
        return format_failure(FormatFailureKind.TRUNCATED, RuleId("truncated_reply"))
    return None


def blank_reply(reply: Reply, context: ReadContext) -> Reading | None:
    if not reply.text.strip():
        return format_failure(FormatFailureKind.EMPTY, RuleId("blank_reply"))
    return None


def oversized_number(reply: Reply, context: ReadContext) -> Reading | None:
    """A run of ten or more digits is ambiguous, never a rating."""
    if OVERSIZED_NUMBER_PATTERN.search(reply.text):
        return format_failure(FormatFailureKind.AMBIGUOUS, RuleId("oversized_number"))
    return None


def is_integer(number: str) -> bool:
    return INTEGER_PATTERN.fullmatch(number) is not None


def lone_integer_match(text: str) -> re.Match[str] | None:
    """The match of the one integer `text` holds, with decoration but no words or rivals; its group 1 is the integer."""
    match = BARE_NUMBER_PATTERN.match(text)
    if match is None or not is_integer(match.group(1)):
        return None
    return match


def decline_evidence(text: str) -> Span | None:
    """Where decline wording first appears in `text`, or None; a modal before agree or disagree is a position."""
    matches = [match for pattern in DECLINE_PATTERNS if (match := pattern.search(text))]
    if not matches:
        return None
    first = min(matches, key=lambda match: match.start())
    return Span(start=first.start(), end=first.end())


def lone_integer(text: str, offset: int, context: ReadContext, rule: RuleId, hedge: Span | None) -> Reading | None:
    """The reading of the one integer `text` holds; `offset` places it in the reply, `hedge` is the reply's."""
    match = lone_integer_match(text)
    if match is None:
        return None
    span = Span(start=offset + match.start(1), end=offset + match.end(1))
    return rating_reading(int(match.group(1)), span, rule, context, hedge)


def bare_integer(reply: Reply, context: ReadContext) -> Reading | None:
    """A reply that is one integer and nothing else has no room for a hedge."""
    return lone_integer(reply.text, 0, context, RuleId("bare_integer"), None)


def edge_lines(text: str) -> tuple[re.Match[str], ...]:
    """The first and last non-empty lines, once each."""
    lines = list(NON_EMPTY_LINE_PATTERN.finditer(text))
    return tuple(lines[:1] + lines[1:][-1:])


def committed_integers(text: str) -> set[int]:
    """Every integer a lone first or last line, or an anchoring phrase, commits to."""
    edges = (lone_integer_match(line.group()) for line in edge_lines(text))
    anchored = (match.group(1) for match in ANCHORED_RATING_PATTERN.finditer(text))
    return {int(match.group(1)) for match in edges if match is not None} | {
        int(number) for number in anchored if is_integer(number)
    }


def conflicting_commitments(reply: Reply, context: ReadContext) -> Reading | None:
    """Commitments that name different integers, such as `2` on the first line and `4` on the last, are ambiguous."""
    if len(committed_integers(reply.text)) > 1:
        return format_failure(FormatFailureKind.AMBIGUOUS, RuleId("conflicting_commitments"))
    return None


def edge_line_integer(reply: Reply, context: ReadContext) -> Reading | None:
    """A bare integer on the first or last line is a commitment; decline wording elsewhere in the reply is a hedge."""
    for line in edge_lines(reply.text):
        reading = lone_integer(
            line.group(), line.start(), context, RuleId("edge_line_integer"), decline_evidence(reply.text)
        )
        if reading is not None:
            return reading
    return None


def anchored_phrase(reply: Reply, context: ReadContext) -> Reading | None:
    """A rating named by an anchoring phrase, such as "my rating is 4"; every such phrase must name it."""
    matches = list(ANCHORED_RATING_PATTERN.finditer(reply.text))
    if not matches or not all(is_integer(match.group(1)) for match in matches):
        return None
    if len({int(match.group(1)) for match in matches}) != 1:
        return None
    last = matches[-1]
    span = Span(start=last.start(1), end=last.end(1))
    return rating_reading(int(last.group(1)), span, RuleId("anchored_phrase"), context, decline_evidence(reply.text))


def decline_wording(reply: Reply, context: ReadContext) -> Reading | None:
    """Decline wording in a reply that names no integer or several.

    agreeing_integers runs first, so "I can't say I agree. 2" reads 2, with the wording kept as a hedge."""
    evidence = decline_evidence(reply.text)
    if evidence is None:
        return None
    return DeclineRead(kind=ReadingKind.DECLINE, evidence=evidence, rule=RuleId("decline_wording"))


def agreeing_integers(reply: Reply, context: ReadContext) -> Reading | None:
    """Every number in the reply is the same integer; the last occurrence is where the reply left it."""
    matches = list(NUMBER_TOKEN_PATTERN.finditer(reply.text))
    if not matches or not all(is_integer(match.group()) for match in matches):
        return None
    if len({int(match.group()) for match in matches}) != 1:
        return None
    last = matches[-1]
    span = Span(start=last.start(), end=last.end())
    return rating_reading(int(last.group()), span, RuleId("agreeing_integers"), context, decline_evidence(reply.text))


def no_digit(reply: Reply, context: ReadContext) -> Reading | None:
    if NUMBER_TOKEN_PATTERN.search(reply.text) is None:
        return format_failure(FormatFailureKind.NO_DIGIT, RuleId("no_digit"))
    return None


FREE_TEXT_RULES: Final[tuple[ReadRule, ...]] = (
    truncated_decline,
    truncated_reply,
    blank_reply,
    oversized_number,
    bare_integer,
    conflicting_commitments,
    edge_line_integer,
    anchored_phrase,
    agreeing_integers,
    decline_wording,
    no_digit,
)
