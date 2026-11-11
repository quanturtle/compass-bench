import pytest

from compass_bench.domain.instrument.scale import Scale, ScaleTooShort, forced_choice
from tests.builders.instrument import FIVE_POINT_LABELS, FOUR_POINT_LABELS, THREE_POINT_LABELS


def test_forced_choice_drops_the_midpoint() -> None:
    assert forced_choice(Scale(labels=FIVE_POINT_LABELS)) == Scale(labels=FOUR_POINT_LABELS)


def test_forced_choice_keeps_an_even_scale() -> None:
    assert forced_choice(Scale(labels=FOUR_POINT_LABELS)) == Scale(labels=FOUR_POINT_LABELS)


def test_forced_choice_refuses_a_three_point_scale() -> None:
    with pytest.raises(ScaleTooShort):
        forced_choice(Scale(labels=THREE_POINT_LABELS))
