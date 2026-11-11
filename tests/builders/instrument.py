"""Scales and questionnaires."""

from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair, PolarityPair
from compass_bench.domain.ids import QuestionId
from compass_bench.domain.instrument.compass import Axis, Compass
from compass_bench.domain.instrument.questionnaire import Question, Questionnaire
from compass_bench.domain.instrument.scale import Scale

FIVE_POINT_LABELS: Final = ("Strongly disagree", "Disagree", "Neither agree nor disagree", "Agree", "Strongly agree")
FOUR_POINT_LABELS: Final = ("Strongly disagree", "Disagree", "Agree", "Strongly agree")
THREE_POINT_LABELS: Final = ("Disagree", "Neither agree nor disagree", "Agree")
TWO_POINT_LABELS: Final = ("Disagree", "Agree")

COMPASS: Final = Compass(
    axes=AxisPair(
        x=Axis(name="left vs right", negative="left", positive="right"),
        y=Axis(name="libertarian vs authoritarian", negative="libertarian", positive="authoritarian"),
    )
)


def build_question(question: str, axis: AxisKey, facet: str | None = None) -> Question:
    """A question on `axis`; its facet is `facet`, or one named after the axis, so the two axes share none."""
    return Question(
        id=QuestionId(question),
        axis=axis,
        facet=facet if facet is not None else f"{axis} facet",
        statements=PolarityPair(negative=f"{question} leans negative.", positive=f"{question} leans positive."),
    )


def build_questionnaire(questions: tuple[Question, ...], labels: tuple[str, ...]) -> Questionnaire:
    return Questionnaire(
        title="Test questionnaire", compass=COMPASS, scale=Scale(labels=labels), questions=questions, author="Jane Doe"
    )


def asked_scales() -> tuple[Scale, ...]:
    """Scales of 3 to 7 labels, odd and even; a forced-choice scale asks on one of these label counts too."""
    return tuple(Scale(labels=tuple(f"label {index}" for index in range(count))) for count in range(3, 8))


def questions_per_axis(count: int) -> tuple[Question, ...]:
    """`count` questions on each axis, ids `x-00`, `y-00`, and so on."""
    return tuple(build_question(f"{axis}-{index:02d}", axis) for axis in AxisKey for index in range(count))
