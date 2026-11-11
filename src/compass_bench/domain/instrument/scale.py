"""Response scales. Labels are stored in canonical order: strongest disagreement first."""

from typing import Final, NewType

from compass_bench.domain.value import Value

CanonicalRating = NewType("CanonicalRating", int)
DisplayedRating = NewType("DisplayedRating", int)

# strongly disagree, disagree, agree, strongly agree
MIN_FORCED_CHOICE_POINTS: Final = 4


class ScaleTooShort(Exception):
    """A forced-choice scale needs at least four options."""


class Scale(Value):
    """An odd label count has a neutral midpoint; an even count forces a side, as a 4-point scale does."""

    labels: tuple[str, ...]


def points(scale: Scale) -> int:
    return len(scale.labels)


def center(scale: Scale) -> float:
    """The midpoint of canonical ratings 1 to K: a rating on an odd scale, between two on an even one."""
    return (points(scale) + 1) / 2


def normalize(scale: Scale, rating: CanonicalRating) -> float:
    """Map a canonical rating onto [-1, 1], with 0 at the scale's center: 1 maps to -1 and K to +1."""
    return (rating - center(scale)) / (center(scale) - 1)


def forced_choice(scale: Scale) -> Scale:
    """Drop an odd scale's neutral midpoint and keep an even scale as it is; raises ScaleTooShort below four points."""
    labels = scale.labels
    if len(labels) % 2 == 1:
        middle = len(labels) // 2
        labels = labels[:middle] + labels[middle + 1 :]
    if len(labels) < MIN_FORCED_CHOICE_POINTS:
        raise ScaleTooShort(f"forced choice leaves {len(labels)} options; it needs {MIN_FORCED_CHOICE_POINTS}")
    return Scale(labels=labels)
