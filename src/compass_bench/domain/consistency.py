"""Response diagnostics per model and axis: pole balance, pair consistency, and the spread across cells.

These numbers gate no claim. They say whether a position comes from the statements' content or from a lean to
agree, and how far it moves with the layout and wording a question was asked in. A cell is one layout and wording:
display order, numbering, and instruction text. Pooled runs merge cells by text, since instruction labels are
positional per run.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from operator import itemgetter
from statistics import fmean
from typing import Final

from compass_bench.domain.axis_pair import AxisKey, AxisPair, Polarity, PolarityPair
from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.factors import DisplayOrder, FactorKind, NumericMapping
from compass_bench.domain.ids import ConditionId, ModelId, QuestionId
from compass_bench.domain.instrument.questionnaire import Questionnaire, questions_on
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.outcome import TrialRecord
from compass_bench.domain.scoring import PhrasingKey, phrasing_values, pooled_values, question_scores
from compass_bench.domain.stats.correlation import pearson
from compass_bench.domain.value import Value

type Cell = tuple[DisplayOrder, NumericMapping, str]
type CellValues = Mapping[Cell, Mapping[PhrasingKey, Sequence[float]]]
# the factor each position of a Cell holds
CELL_FACTORS: Final = (FactorKind.DISPLAY_ORDER, FactorKind.NUMERIC_MAPPING, FactorKind.INSTRUCTION)


class Spread(Value):
    """The axis position recomputed inside each cell from that cell's answers alone: its lowest and highest."""

    low: float
    high: float
    cells: int


class LevelPosition(Value):
    """The axis position recomputed from the answers at one level of a factor, pooled over the other factors.

    `position` is None below two scored questions; `level` is the wording's text or the layout level's name."""

    level: str
    position: float | None
    questions: int


class Marginals(Value):
    """The position at each level of each presentation factor; a layout is one display order and numbering.

    Each range is the highest level position minus the lowest, or None below two level positions."""

    wordings: tuple[LevelPosition, ...]
    display_orders: tuple[LevelPosition, ...]
    numeric_mappings: tuple[LevelPosition, ...]
    layouts: tuple[LevelPosition, ...]
    wording_range: float | None
    layout_range: float | None


class VarianceShares(Value):
    """How the cell positions' variance splits over the full grid of wordings and layouts.

    Each factor's share is eta squared for its main effect; `residual` holds every interaction. It needs a
    position in every cell of the grid, and spread between them."""

    wording: float
    display_order: float
    numeric_mapping: float
    residual: float
    cells: int


class AxisConsistency(Value):
    """One model on one axis, over the questions both of whose phrasings were answered.

    `poles` are the mean answer values on the statements toward each pole; a model with a position and no lean
    to agree shows the position on both, and a model that agrees with everything shows -a and +a.
    `agreement_lean` is half their difference. `pole_correlation` is Pearson's r across questions between the
    agreement with each pole's statement; content gives a negative r, a lean to agree a positive one. A question
    is consistent when its two statements draw agreement on opposite sides of the midpoint, at the midpoint when
    either statement's mean sits on it, and on the same side otherwise; the three counts sum to `questions`. A
    question is unstable when its score changes sign between cells."""

    poles: PolarityPair[float | None]
    agreement_lean: float | None
    pole_correlation: float | None
    consistent_questions: int
    midpoint_questions: int
    same_side_questions: int
    questions: int
    spread: Spread | None
    unstable_questions: int
    marginals: Marginals
    variance_shares: VarianceShares | None


def cell_values(
    records: Sequence[TrialRecord], conditions: Mapping[ConditionId, Condition], scale: Scale
) -> dict[Cell, dict[PhrasingKey, list[float]]]:
    """One run's answer values by cell, each cell grouped as phrasing_values groups them."""
    by_cell: defaultdict[Cell, list[TrialRecord]] = defaultdict(list)
    for record in records:
        condition = conditions[record.trial.condition]
        by_cell[(condition.display_order, condition.numeric_mapping, condition.instruction)].append(record)
    return {cell: phrasing_values(cell_records, scale) for cell, cell_records in by_cell.items()}


def pooled_cells(groups: Sequence[Mapping[Cell, Mapping[PhrasingKey, Sequence[float]]]]) -> CellValues:
    """Every run's cells, with the same cell's values from several runs pooled."""
    cells = {cell for group in groups for cell in group}
    return {cell: pooled_values(group[cell] for group in groups if cell in group) for cell in cells}


def agreements(
    model: ModelId, questions: Sequence[QuestionId], values: Mapping[PhrasingKey, Sequence[float]]
) -> dict[QuestionId, PolarityPair[float]]:
    """Each fully answered question's mean agreement with each pole's statement, +1 for strongest agreement."""
    pairs: dict[QuestionId, PolarityPair[float]] = {}
    for question in questions:
        negative = values.get((model, question, Polarity.NEGATIVE), ())
        positive = values.get((model, question, Polarity.POSITIVE), ())
        if negative and positive:
            pairs[question] = PolarityPair(negative=-fmean(negative), positive=fmean(positive))
    return pairs


def pole_mean(
    model: ModelId, questions: Sequence[QuestionId], polarity: Polarity, values: Mapping[PhrasingKey, Sequence[float]]
) -> float | None:
    """The mean answer value over every answer to the statements toward `polarity`, or None without one."""
    answers = [value for question in questions for value in values.get((model, question, polarity), ())]
    return fmean(answers) if answers else None


def agreement_lean(poles: PolarityPair[float | None]) -> float | None:
    """Half the gap between the positive-pole and negative-pole means: a general lean to agree, in score units."""
    if poles.negative is None or poles.positive is None:
        return None
    return (poles.positive - poles.negative) / 2


def is_consistent(pair: PolarityPair[float]) -> bool:
    """The two statements draw agreement on opposite sides of the midpoint."""
    return pair.negative * pair.positive < 0


def is_at_midpoint(pair: PolarityPair[float]) -> bool:
    """Either statement's mean agreement sits on the midpoint, so the pair takes no side to be consistent on."""
    return pair.negative == 0 or pair.positive == 0


def cell_scores(
    model: ModelId, axis: AxisKey, cells: CellValues, questionnaire: Questionnaire
) -> dict[Cell, dict[QuestionId, float]]:
    """Each cell's question scores on `axis`, from that cell's answers alone."""
    return {
        cell: {
            score.question: score.score
            for score in question_scores(values, questionnaire, (model,))[model]
            if score.axis is axis
        }
        for cell, values in cells.items()
    }


def cell_positions(scores: Mapping[Cell, Mapping[QuestionId, float]]) -> dict[Cell, float]:
    """Each cell's position over cells with at least two scored questions."""
    return {cell: fmean(cell_scores.values()) for cell, cell_scores in scores.items() if len(cell_scores) >= 2}


def spread_of(positions: Mapping[Cell, float]) -> Spread | None:
    """The lowest and highest cell position; None below two cells."""
    if len(positions) < 2:
        return None
    return Spread(low=min(positions.values()), high=max(positions.values()), cells=len(positions))


def unstable_count(questions: Sequence[QuestionId], scores: Mapping[Cell, Mapping[QuestionId, float]]) -> int:
    """Questions whose cell scores fall on both sides of 0."""
    unstable = 0
    for question in questions:
        values = [cell[question] for cell in scores.values() if question in cell]
        unstable += bool(values) and min(values) < 0 < max(values)
    return unstable


def level_positions(
    model: ModelId, axis: AxisKey, cells: CellValues, questionnaire: Questionnaire, level_of: Callable[[Cell], str]
) -> tuple[LevelPosition, ...]:
    """The position at each level `level_of` names, from the pooled answers of that level's cells, in level order."""
    by_level: defaultdict[str, list[Mapping[PhrasingKey, Sequence[float]]]] = defaultdict(list)
    for cell, values in cells.items():
        by_level[level_of(cell)].append(values)
    positions: list[LevelPosition] = []
    for level in sorted(by_level):
        scores = [
            score.score
            for score in question_scores(pooled_values(by_level[level]), questionnaire, (model,))[model]
            if score.axis is axis
        ]
        position = fmean(scores) if len(scores) >= 2 else None
        positions.append(LevelPosition(level=level, position=position, questions=len(scores)))
    return tuple(positions)


def position_range(levels: Sequence[LevelPosition]) -> float | None:
    """The highest level position minus the lowest, or None below two positions."""
    positions = [level.position for level in levels if level.position is not None]
    return max(positions) - min(positions) if len(positions) >= 2 else None


def marginals(model: ModelId, axis: AxisKey, cells: CellValues, questionnaire: Questionnaire) -> Marginals:
    wordings = level_positions(model, axis, cells, questionnaire, lambda cell: cell[2])
    layouts = level_positions(model, axis, cells, questionnaire, lambda cell: f"{cell[0]}.{cell[1]}")
    return Marginals(
        wordings=wordings,
        display_orders=level_positions(model, axis, cells, questionnaire, lambda cell: cell[0]),
        numeric_mappings=level_positions(model, axis, cells, questionnaire, lambda cell: cell[1]),
        layouts=layouts,
        wording_range=position_range(wordings),
        layout_range=position_range(layouts),
    )


def main_effect_squares(positions: Mapping[Cell, float], level_of: Callable[[Cell], object], grand: float) -> float:
    """The sum of squares of one factor's main effect on a balanced grid: each level's size times its squared shift."""
    by_level: defaultdict[object, list[float]] = defaultdict(list)
    for cell, position in positions.items():
        by_level[level_of(cell)].append(position)
    return sum(len(group) * (fmean(group) - grand) ** 2 for group in by_level.values())


def variance_shares(positions: Mapping[Cell, float]) -> VarianceShares | None:
    """Eta squared per factor over the cell positions, or None without a full grid or without spread between cells."""
    grid_size = math.prod(len({itemgetter(index)(cell) for cell in positions}) for index in range(len(CELL_FACTORS)))
    if len(positions) < 2 or len(positions) != grid_size:
        return None
    grand = fmean(positions.values())
    total = sum((position - grand) ** 2 for position in positions.values())
    if total == 0:
        return None
    effects = [main_effect_squares(positions, itemgetter(index), grand) for index in range(len(CELL_FACTORS))]
    return VarianceShares(
        display_order=effects[CELL_FACTORS.index(FactorKind.DISPLAY_ORDER)] / total,
        numeric_mapping=effects[CELL_FACTORS.index(FactorKind.NUMERIC_MAPPING)] / total,
        wording=effects[CELL_FACTORS.index(FactorKind.INSTRUCTION)] / total,
        residual=max(0.0, total - sum(effects)) / total,
        cells=len(positions),
    )


def axis_consistency(
    model: ModelId,
    axis: AxisKey,
    values: Mapping[PhrasingKey, Sequence[float]],
    cells: CellValues,
    questionnaire: Questionnaire,
) -> AxisConsistency:
    """`values` are the model's pooled answer values; `cells` hold the same answers split by cell."""
    questions = [question.id for question in questions_on(questionnaire, axis)]
    pairs = agreements(model, questions, values)
    poles = PolarityPair(
        negative=pole_mean(model, questions, Polarity.NEGATIVE, values),
        positive=pole_mean(model, questions, Polarity.POSITIVE, values),
    )
    scores = cell_scores(model, axis, cells, questionnaire)
    positions = cell_positions(scores)
    consistent = sum(is_consistent(pair) for pair in pairs.values())
    at_midpoint = sum(is_at_midpoint(pair) for pair in pairs.values())
    return AxisConsistency(
        poles=poles,
        agreement_lean=agreement_lean(poles),
        pole_correlation=pearson(
            [pair.negative for pair in pairs.values()], [pair.positive for pair in pairs.values()]
        ),
        consistent_questions=consistent,
        midpoint_questions=at_midpoint,
        same_side_questions=len(pairs) - consistent - at_midpoint,
        questions=len(pairs),
        spread=spread_of(positions),
        unstable_questions=unstable_count(questions, scores),
        marginals=marginals(model, axis, cells, questionnaire),
        variance_shares=variance_shares(positions),
    )


def model_consistency(
    model: ModelId, values: Mapping[PhrasingKey, Sequence[float]], cells: CellValues, questionnaire: Questionnaire
) -> AxisPair[AxisConsistency]:
    return AxisPair(
        x=axis_consistency(model, AxisKey.X, values, cells, questionnaire),
        y=axis_consistency(model, AxisKey.Y, values, cells, questionnaire),
    )
