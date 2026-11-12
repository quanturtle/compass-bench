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
# a sign is a hyphen or the minus sign U+2212 touching the digit; a spaced hyphen is a bullet or a separator
MINUS_SIGN: Final = "−"
NUMBER: Final = rf"[-+{MINUS_SIGN}]?(?:[0-9]{{1,9}}(?:\.[0-9]{{1,9}})?|\.[0-9]{{1,9}})(?:[eE][-+]?[0-9]{{1,9}})?"
INTEGER_PATTERN: Final = re.compile(rf"[-+{MINUS_SIGN}]?[0-9]{{1,9}}")
OVERSIZED_NUMBER_PATTERN: Final = re.compile(r"[0-9]{10}")
BARE_NUMBER_PATTERN: Final = re.compile(rf"^[\s\W]*?({NUMBER})[\s\W]*$")
NON_EMPTY_LINE_PATTERN: Final = re.compile(r"[^\r\n]*\S[^\r\n]*")

# the lookbehind keeps "1-5" reading as 1 and 5, not 1 and -5
NUMBER_TOKEN_PATTERN: Final = re.compile(rf"(?<![0-9]){NUMBER}")
RANGE_SEPARATOR: Final = rf"(?:to\b|[-–{MINUS_SIGN}])"
# the scale's own range may stand between the anchor and its number, as in "Rating 1-5: 4"
SCALE_RANGE: Final = rf"(?:\s*\(?\s*[0-9]{{1,9}}\s*{RANGE_SEPARATOR}\s*[0-9]{{1,9}}\s*\)?)?"
ANCHORED_RATING_PATTERN: Final = re.compile(
    rf"(?:answer|rating){SCALE_RANGE}\s*(?:is\b|:|=)?\s*({NUMBER})", re.IGNORECASE
)
# a second number offered after the first, as in "2 or 3" and "1 to 5", commits to neither
ALTERNATIVE_PATTERN: Final = re.compile(rf"\s*(?:or\b|{RANGE_SEPARATOR})\s*{NUMBER}", re.IGNORECASE)
# "not 4" rules a number out; it does not choose one
NEGATION_PATTERN: Final = re.compile(r"\b(?:not|never)\s+(?:(?:a|an|quite|exactly|really)\s+)*$", re.IGNORECASE)
CLAUSE_BREAK_PATTERN: Final = re.compile(r"[.,;:!?\r\n]")

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


def integer_value(number: str) -> int:
    """The value of an integer token; int() does not accept the minus sign U+2212."""
    return int(number.replace(MINUS_SIGN, "-"))


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
    return rating_reading(integer_value(match.group(1)), span, rule, context, hedge)


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
    return {integer_value(match.group(1)) for match in edges if match is not None} | {
        integer_value(number) for number in anchored if is_integer(number)
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


def offers_alternative(text: str, number: Span) -> bool:
    """Whether a second number follows as an alternative or a range end, as in "2 or 3" and "1 to 5"."""
    return ALTERNATIVE_PATTERN.match(text, number.end) is not None


def is_declined(text: str, number: Span) -> bool:
    """Whether decline wording governs the number: it stands before it with no clause break between.

    "I can't pick just 1 number" declines; "I can't say I agree. 2" and "4, though I can't be sure" commit."""
    return any(
        match.end() <= number.start and CLAUSE_BREAK_PATTERN.search(text, match.end(), number.start) is None
        for pattern in DECLINE_PATTERNS
        for match in pattern.finditer(text)
    )


def anchored_phrase(reply: Reply, context: ReadContext) -> Reading | None:
    """A rating named by an anchoring phrase, such as "my rating is 4"; every such phrase must name it.

    A phrase that offers an alternative, or that decline wording governs, commits to nothing."""
    matches = list(ANCHORED_RATING_PATTERN.finditer(reply.text))
    if not matches or not all(is_integer(match.group(1)) for match in matches):
        return None
    if len({integer_value(match.group(1)) for match in matches}) != 1:
        return None
    spans = [Span(start=match.start(1), end=match.end(1)) for match in matches]
    if any(offers_alternative(reply.text, span) or is_declined(reply.text, span) for span in spans):
        return None
    value = integer_value(matches[-1].group(1))
    return rating_reading(value, spans[-1], RuleId("anchored_phrase"), context, decline_evidence(reply.text))


def decline_wording(reply: Reply, context: ReadContext) -> Reading | None:
    """Decline wording in a reply that names no integer, several, or one the wording governs.

    agreeing_integers runs first, so "I can't say I agree. 2" reads 2, with the wording kept as a hedge."""
    evidence = decline_evidence(reply.text)
    if evidence is None:
        return None
    return DeclineRead(kind=ReadingKind.DECLINE, evidence=evidence, rule=RuleId("decline_wording"))


def is_negated(text: str, number: Span) -> bool:
    """Whether "not" or "never" stands directly before the number, as in "Not 4."."""
    return NEGATION_PATTERN.search(text, 0, number.start) is not None


def agreeing_integers(reply: Reply, context: ReadContext) -> Reading | None:
    """Every number in the reply is the same integer; the last occurrence is where the reply left it.

    A number that is negated, or that decline wording governs, commits to nothing."""
    matches = list(NUMBER_TOKEN_PATTERN.finditer(reply.text))
    if not matches or not all(is_integer(match.group()) for match in matches):
        return None
    if len({integer_value(match.group()) for match in matches}) != 1:
        return None
    spans = [Span(start=match.start(), end=match.end()) for match in matches]
    if any(is_negated(reply.text, span) or is_declined(reply.text, span) for span in spans):
        return None
    value = integer_value(matches[-1].group())
    return rating_reading(value, spans[-1], RuleId("agreeing_integers"), context, decline_evidence(reply.text))


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
