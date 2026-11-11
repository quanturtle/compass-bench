import pytest

from compass_bench.domain.axis_pair import AxisKey, PolarityPair
from compass_bench.domain.findings import FindingCode, Severity
from compass_bench.domain.instrument.questionnaire import find_problems, questionnaire_hash
from tests.builders.instrument import (
    FIVE_POINT_LABELS,
    TWO_POINT_LABELS,
    build_question,
    build_questionnaire,
    questions_per_axis,
)


def test_reordering_the_questions_or_editing_the_author_makes_a_new_hash() -> None:
    questionnaire = build_questionnaire(questions_per_axis(2), FIVE_POINT_LABELS)
    reordered = questionnaire.model_copy(update={"questions": questionnaire.questions[::-1]})
    reauthored = questionnaire.model_copy(update={"author": "John Doe"})

    hashes = {questionnaire_hash(edit) for edit in (questionnaire, reordered, reauthored)}

    assert len(hashes) == 3


def test_find_problems_returns_every_failing_check() -> None:
    repeated = build_question("x-00", AxisKey.X)
    questionnaire = build_questionnaire((repeated, repeated), TWO_POINT_LABELS)

    codes = [finding.code for finding in find_problems(questionnaire)]

    assert codes == [FindingCode.DUPLICATE_QUESTION, FindingCode.EMPTY_AXIS, FindingCode.SCALE_TOO_SHORT]


def test_a_facet_named_on_both_axes_is_an_error() -> None:
    questions = (build_question("x-00", AxisKey.X, "shared"), build_question("y-00", AxisKey.Y, "shared"))

    findings = find_problems(build_questionnaire(questions, FIVE_POINT_LABELS))

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.ERROR, FindingCode.FACET_ON_BOTH_AXES)
    ]


@pytest.mark.parametrize("statement", ["The state should not tax.", "The state never taxes.", "Owners shouldn’t pay."])
def test_a_negated_statement_draws_a_warning(statement: str) -> None:
    question = build_question("x-00", AxisKey.X).model_copy(
        update={"statements": PolarityPair(negative=statement, positive="The state taxes.")}
    )

    findings = find_problems(build_questionnaire((question, build_question("y-00", AxisKey.Y)), FIVE_POINT_LABELS))

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.WARNING, FindingCode.NEGATED_STATEMENT)
    ]


@pytest.mark.parametrize(
    "statement", ["The state should tax so that services are funded.", "Police may search in order to prevent crime."]
)
def test_a_statement_that_justifies_its_policy_draws_a_warning(statement: str) -> None:
    question = build_question("x-00", AxisKey.X).model_copy(
        update={"statements": PolarityPair(negative=statement, positive="The state taxes.")}
    )

    findings = find_problems(build_questionnaire((question, build_question("y-00", AxisKey.Y)), FIVE_POINT_LABELS))

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.WARNING, FindingCode.JUSTIFYING_CLAUSE)
    ]


def test_facets_of_unequal_size_on_an_axis_draw_one_warning_for_that_axis() -> None:
    questions = (
        build_question("x-00", AxisKey.X, "a"),
        build_question("x-01", AxisKey.X, "a"),
        build_question("x-02", AxisKey.X, "b"),
        build_question("y-00", AxisKey.Y, "c"),
        build_question("y-01", AxisKey.Y, "d"),
    )

    findings = find_problems(build_questionnaire(questions, FIVE_POINT_LABELS))

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.WARNING, FindingCode.UNEQUAL_FACETS)
    ]
    assert findings[0].message.startswith("axis x's facets hold 1 to 2 questions")


def test_a_word_that_only_contains_a_negation_does_not_warn() -> None:
    question = build_question("x-00", AxisKey.X).model_copy(
        update={"statements": PolarityPair(negative="Note the knot.", positive="Nothing to see.")}
    )

    assert find_problems(build_questionnaire((question, build_question("y-00", AxisKey.Y)), FIVE_POINT_LABELS)) == ()
