"""Two axes, each with a negative and a positive pole."""

from compass_bench.domain.axis_pair import AxisPair, Polarity
from compass_bench.domain.value import Value


class Axis(Value):
    """`negative` and `positive` are the labels of the axis's two poles."""

    name: str
    negative: str
    positive: str

    def pole(self, polarity: Polarity) -> str:
        """The label of the pole on that side."""
        match polarity:
            case Polarity.NEGATIVE:
                return self.negative
            case Polarity.POSITIVE:
                return self.positive


class Compass(Value):
    axes: AxisPair[Axis]
