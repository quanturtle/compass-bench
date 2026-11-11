import pytest

from compass_bench.domain.design.experiment import AnswerType, ScaleChoice
from compass_bench.domain.design.factors import FactorKind, InstructionFactor
from compass_bench.domain.design.preflight import (
    plan_findings,
    summarize_plan,
    support_findings,
    trial_count,
    uniform_half_width,
)
from compass_bench.domain.findings import FindingCode
from compass_bench.domain.ids import ModelId
from compass_bench.domain.instrument.scale import Scale
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec, build_spec
from tests.builders.instrument import FIVE_POINT_LABELS, THREE_POINT_LABELS, build_questionnaire, questions_per_axis


def test_trial_count_crosses_models_questions_phrasings_conditions_and_repetitions() -> None:
    questionnaire = build_questionnaire(questions_per_axis(3), FIVE_POINT_LABELS)
    models = {
        ModelId("free"): build_model_spec(AnswerType.FREE_TEXT),
        ModelId("structured"): build_model_spec(AnswerType.STRUCTURED),
    }
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS, repetitions=2))

    assert trial_count(spec, questionnaire) == 2 * 6 * 2 * 4 * 2


def test_a_factor_kind_that_is_not_varied_draws_a_warning() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    models = {ModelId("free"): build_model_spec(AnswerType.FREE_TEXT)}
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS[:1], repetitions=1))

    codes = [finding.code for finding in plan_findings(spec, questionnaire)]

    assert codes == [FindingCode.UNVARIED_FACTOR, FindingCode.SINGLE_WORDING]


def test_a_design_that_asks_in_several_wordings_draws_no_wording_warning() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    models = {ModelId("free"): build_model_spec(AnswerType.FREE_TEXT)}
    wordings = InstructionFactor(kind=FactorKind.INSTRUCTION, levels=("Rate this statement.", "Your view?"))
    spec = build_spec(questionnaire, models, build_design((*BOTH_FACTORS, wordings), repetitions=1))

    assert plan_findings(spec, questionnaire) == ()


def test_forced_choice_on_a_three_point_scale_is_an_error() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), THREE_POINT_LABELS)
    models = {ModelId("free"): build_model_spec(AnswerType.FREE_TEXT)}
    design = build_design(BOTH_FACTORS, repetitions=1).model_copy(update={"scale": ScaleChoice.FORCED_CHOICE})

    codes = [finding.code for finding in plan_findings(build_spec(questionnaire, models, design), questionnaire)]

    assert codes == [FindingCode.SINGLE_WORDING, FindingCode.SCALE_TOO_SHORT]


def test_an_axis_below_the_question_floor_draws_a_warning() -> None:
    questionnaire = build_questionnaire(questions_per_axis(9), FIVE_POINT_LABELS)
    models = {ModelId("free"): build_model_spec(AnswerType.FREE_TEXT)}
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS, repetitions=1))

    codes = [finding.code for finding in support_findings(spec, questionnaire)]

    assert codes == [FindingCode.BELOW_QUESTION_FLOOR, FindingCode.BELOW_QUESTION_FLOOR]


def test_a_random_responders_half_width_follows_the_scale_the_cells_and_the_question_count() -> None:
    five = Scale(labels=FIVE_POINT_LABELS)

    assert uniform_half_width(five, cells=4, repetitions=1, questions=12, level=0.975) == pytest.approx(0.187, abs=1e-3)
    assert uniform_half_width(five, cells=4, repetitions=1, questions=33, level=0.975) == pytest.approx(0.102, abs=1e-3)
    assert uniform_half_width(five, cells=4, repetitions=1, questions=1, level=0.975) is None


def test_the_plan_summary_carries_the_random_responders_half_width_per_axis() -> None:
    questionnaire = build_questionnaire(questions_per_axis(12), FIVE_POINT_LABELS)
    spec = build_spec(
        questionnaire,
        {ModelId("free"): build_model_spec(AnswerType.FREE_TEXT)},
        build_design(BOTH_FACTORS, repetitions=1),
    )

    summary = summarize_plan(spec, questionnaire, ())

    assert summary.uniform_half_width.x == pytest.approx(0.187, abs=1e-3)
    assert summary.uniform_half_width.y == summary.uniform_half_width.x
