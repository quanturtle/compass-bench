"""Trials and their dispatch order: a seeded randomized block design, one round per repetition."""

import random

from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.design.experiment import ExperimentSpec, design_conditions
from compass_bench.domain.ids import ConditionId, ModelId, QuestionId, RunId, TrialKey, trial_key
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.value import Value


class TrialCell(Value):
    """One model × question × phrasing × condition × repetition cell of the design."""

    model: ModelId
    question: QuestionId
    polarity: Polarity
    condition: ConditionId
    repetition: int


class Trial(Value):
    """`polarity` picks the question's phrasing: the statement that leans toward that pole."""

    key: TrialKey
    model: ModelId
    question: QuestionId
    polarity: Polarity
    condition: ConditionId
    repetition: int
    position: int


def expand_cells(spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[TrialCell, ...]:
    """Every cell in canonical order: models by id, then questions as listed, phrasings, and conditions."""
    conditions = design_conditions(spec.design)
    return tuple(
        TrialCell(
            model=model,
            question=question.id,
            polarity=polarity,
            condition=condition.id,
            repetition=repetition,
        )
        for repetition in range(spec.design.repetitions_per_condition)
        for model in sorted(spec.models)
        for question in questionnaire.questions
        for polarity in Polarity
        for condition in conditions
    )


def interleave(cells: tuple[TrialCell, ...], seed: int) -> tuple[TrialCell, ...]:
    """Order cells round by round; each round shuffles models, questions, phrasings, and conditions together."""
    shuffler = random.Random(seed)
    ordered: list[TrialCell] = []
    for repetition in sorted({cell.repetition for cell in cells}):
        round_cells = [cell for cell in cells if cell.repetition == repetition]
        shuffler.shuffle(round_cells)
        ordered.extend(round_cells)
    return tuple(ordered)


def build_schedule(run: RunId, spec: ExperimentSpec, questionnaire: Questionnaire, seed: int) -> tuple[Trial, ...]:
    """Trials in round order. Dispatch follows it; an open circuit or a delayed retry leaves gaps in earlier rounds."""
    return tuple(
        Trial(
            key=trial_key(run, cell.model, cell.question, cell.polarity, cell.condition, cell.repetition),
            model=cell.model,
            question=cell.question,
            polarity=cell.polarity,
            condition=cell.condition,
            repetition=cell.repetition,
            position=position,
        )
        for position, cell in enumerate(interleave(expand_cells(spec, questionnaire), seed))
    )
