"""How far an ordering survives the layouts and wordings: the cells in which a pair's gap keeps the headline sign.

A cell holds one answer per phrasing at one repetition, so a cell's gap is coarse and tests nothing; the count
says whether the headline gap is the same way round under every presentation. Nothing here gates a claim.
"""

from collections.abc import Mapping, Sequence
from statistics import fmean

from compass_bench.domain.axis_pair import AxisKey, AxisPair
from compass_bench.domain.consistency import Cell, CellValues, cell_scores
from compass_bench.domain.ids import ModelId, QuestionId
from compass_bench.domain.inference import Bounded, PairAxis
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.value import Value


class OrderingRobustness(Value):
    """Over the `cells` in which both models score two or more shared questions, how many have a mean gap on the
    headline gap's side of 0."""

    cells: int
    same_sign: int


def cell_gap(first: Mapping[QuestionId, float], second: Mapping[QuestionId, float]) -> float | None:
    """The second model minus the first over the questions both scored in a cell; None below two."""
    shared = [question for question in first if question in second]
    if len(shared) < 2:
        return None
    return fmean(second[question] - first[question] for question in shared)


def cell_gaps(
    first: ModelId, second: ModelId, axis: AxisKey, cells: CellValues, questionnaire: Questionnaire
) -> dict[Cell, float]:
    first_scores = cell_scores(first, axis, cells, questionnaire)
    second_scores = cell_scores(second, axis, cells, questionnaire)
    gaps = {cell: cell_gap(first_scores[cell], second_scores[cell]) for cell in cells}
    return {cell: gap for cell, gap in gaps.items() if gap is not None}


def ordering_robustness(headline: PairAxis, gaps: Sequence[float]) -> OrderingRobustness | None:
    """None when the headline gap is not estimable or its mean is 0, so it has no side to keep."""
    match headline.gap:
        case Bounded(point=point) if point != 0:
            return OrderingRobustness(cells=len(gaps), same_sign=sum(gap * point > 0 for gap in gaps))
        case _:
            return None


def pair_robustness(
    first: ModelId, second: ModelId, pair: AxisPair[PairAxis], cells: CellValues, questionnaire: Questionnaire
) -> AxisPair[OrderingRobustness | None]:
    return AxisPair(
        x=ordering_robustness(pair.x, list(cell_gaps(first, second, AxisKey.X, cells, questionnaire).values())),
        y=ordering_robustness(pair.y, list(cell_gaps(first, second, AxisKey.Y, cells, questionnaire).values())),
    )
