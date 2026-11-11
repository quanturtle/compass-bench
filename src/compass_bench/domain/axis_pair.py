"""Values held once per compass axis or once per pole; no type carries paired x_/y_ fields."""

from collections.abc import Callable
from enum import IntEnum, StrEnum

from compass_bench.domain.value import Value


class AxisKey(StrEnum):
    X = "x"
    Y = "y"


class Polarity(IntEnum):
    """The pole an answer or a position points to: -1 is the negative pole, +1 the positive one."""

    NEGATIVE = -1
    POSITIVE = 1


class AxisPair[T](Value):
    x: T
    y: T

    def get(self, axis: AxisKey) -> T:
        match axis:
            case AxisKey.X:
                return self.x
            case AxisKey.Y:
                return self.y

    def map[U](self, transform: Callable[[T], U]) -> AxisPair[U]:
        return AxisPair(x=transform(self.x), y=transform(self.y))

    def zip[U](self, other: AxisPair[U]) -> AxisPair[tuple[T, U]]:
        return AxisPair(x=(self.x, other.x), y=(self.y, other.y))


class PolarityPair[T](Value):
    negative: T
    positive: T

    def get(self, polarity: Polarity) -> T:
        match polarity:
            case Polarity.NEGATIVE:
                return self.negative
            case Polarity.POSITIVE:
                return self.positive

    def map[U](self, transform: Callable[[T], U]) -> PolarityPair[U]:
        return PolarityPair(negative=transform(self.negative), positive=transform(self.positive))

    def zip[U](self, other: PolarityPair[U]) -> PolarityPair[tuple[T, U]]:
        return PolarityPair(negative=(self.negative, other.negative), positive=(self.positive, other.positive))
