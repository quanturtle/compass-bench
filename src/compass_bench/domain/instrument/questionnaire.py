"""Questions, the questionnaire's content hash, and structural validation."""

import re
from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Final

from pydantic import Field

from compass_bench.domain.axis_pair import AxisKey, Polarity, PolarityPair
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import QuestionId, QuestionnaireHash, content_hash
from compass_bench.domain.instrument.compass import Compass
from compass_bench.domain.instrument.scale import Scale, points
from compass_bench.domain.value import Value

# the fewest labels an authored scale may have: two poles and one point between them
MIN_SCALE_POINTS: Final = 3
# negation words; "no" as a word also matches "no one", which is accepted noise in a warning
NEGATION_PATTERN: Final = re.compile(r"\b(?:not|never|no)\b|n['’]t\b", re.IGNORECASE)
# clauses that justify a policy inside the statement, which tilt the item toward the side that explains itself
JUSTIFICATION_PATTERN: Final = re.compile(
    r"\b(?:so that|in order to|to prevent|to protect|because|even when|even if)\b", re.IGNORECASE
)


class Question(Value):
    """One question on one axis, phrased twice: agreeing with `statements.negative` pulls toward the negative pole.

    Averaging the two phrasings cancels the question's own slant and a model's general lean to agree. `facet` names
    the part of the axis the question covers, so the report can show a position per facet."""

    id: QuestionId
    axis: AxisKey
    facet: Annotated[str, Field(min_length=1)]
    statements: PolarityPair[str]


class Questionnaire(Value):
    """`author` is the author's name."""

    title: str
    compass: Compass
    scale: Scale
    questions: tuple[Question, ...]
    author: str


def questionnaire_hash(questionnaire: Questionnaire) -> QuestionnaireHash:
    """content_hash of every field, title, author, and question order included; any edit makes a new snapshot."""
    return QuestionnaireHash(content_hash(questionnaire.model_dump(mode="json")))


def question_index(questionnaire: Questionnaire) -> Mapping[QuestionId, Question]:
    """Questions by id; duplicate_question_findings rejects a repeated id before any run exists."""
    return {question.id: question for question in questionnaire.questions}


def questions_on(questionnaire: Questionnaire, axis: AxisKey) -> tuple[Question, ...]:
    return tuple(question for question in questionnaire.questions if question.axis is axis)


def duplicate_question_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    counts = Counter(question.id for question in questionnaire.questions)
    return tuple(
        Finding(
            severity=Severity.ERROR,
            code=FindingCode.DUPLICATE_QUESTION,
            message=f"question id {question!r} appears {count} times",
        )
        for question, count in counts.items()
        if count > 1
    )


def empty_axis_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    return tuple(
        Finding(
            severity=Severity.ERROR,
            code=FindingCode.EMPTY_AXIS,
            message=f"axis {axis} ({questionnaire.compass.axes.get(axis).name}) has no questions",
        )
        for axis in AxisKey
        if not questions_on(questionnaire, axis)
    )


def scale_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    count = points(questionnaire.scale)
    if count >= MIN_SCALE_POINTS:
        return ()
    return (
        Finding(
            severity=Severity.ERROR,
            code=FindingCode.SCALE_TOO_SHORT,
            message=f"the scale has {count} labels; it needs at least {MIN_SCALE_POINTS}",
        ),
    )


def facets_on(questionnaire: Questionnaire, axis: AxisKey) -> tuple[str, ...]:
    """The axis's facets, in order of first appearance."""
    return tuple(dict.fromkeys(question.facet for question in questions_on(questionnaire, axis)))


def facet_axis_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """A facet name belongs to one axis; the same name on both would merge two constructs in the report."""
    shared = set(facets_on(questionnaire, AxisKey.X)) & set(facets_on(questionnaire, AxisKey.Y))
    return tuple(
        Finding(
            severity=Severity.ERROR,
            code=FindingCode.FACET_ON_BOTH_AXES,
            message=f"facet {facet!r} is used on both axes",
        )
        for facet in sorted(shared)
    )


def negation_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """A statement that negates reads worse than an affirmative counter-claim; models mishandle negation."""
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.NEGATED_STATEMENT,
            message=f"question {question.id!r}'s statement toward {polarity.name.lower()} contains {match.group()!r}",
        )
        for question in questionnaire.questions
        for polarity in Polarity
        if (match := NEGATION_PATTERN.search(question.statements.get(polarity))) is not None
    )


def justification_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """A statement that carries its policy's justification tilts the item toward the side that explains itself."""
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.JUSTIFYING_CLAUSE,
            message=f"question {question.id!r}'s statement toward {polarity.name.lower()} contains {match.group()!r}",
        )
        for question in questionnaire.questions
        for polarity in Polarity
        if (match := JUSTIFICATION_PATTERN.search(question.statements.get(polarity))) is not None
    )


def facet_balance_findings(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """A position weighs each facet by its question count, so unequal facets weigh the axis toward the larger."""
    findings: list[Finding] = []
    for axis in AxisKey:
        counts = Counter(question.facet for question in questions_on(questionnaire, axis))
        if len(set(counts.values())) > 1:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    code=FindingCode.UNEQUAL_FACETS,
                    message=f"axis {axis}'s facets hold {min(counts.values())} to {max(counts.values())} questions, "
                    "so the position weighs the larger facets more",
                )
            )
    return tuple(findings)


def find_problems(questionnaire: Questionnaire) -> tuple[Finding, ...]:
    """Run every structural check and return all findings."""
    return (
        duplicate_question_findings(questionnaire)
        + empty_axis_findings(questionnaire)
        + scale_findings(questionnaire)
        + facet_axis_findings(questionnaire)
        + negation_findings(questionnaire)
        + justification_findings(questionnaire)
        + facet_balance_findings(questionnaire)
    )
