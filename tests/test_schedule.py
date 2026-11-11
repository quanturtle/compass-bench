from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.design.schedule import build_schedule
from compass_bench.domain.ids import ModelId, run_id
from compass_bench.domain.stats.seeds import schedule_seed
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec, build_spec
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis


def test_the_nonce_determines_the_schedule_and_rounds_run_in_order() -> None:
    questionnaire = build_questionnaire(questions_per_axis(3), FIVE_POINT_LABELS)
    models = {ModelId(name): build_model_spec(AnswerType.FREE_TEXT) for name in ("a", "b")}
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS, repetitions=3))

    first, again, other = (
        build_schedule(run_id(nonce), spec, questionnaire, schedule_seed(nonce))
        for nonce in ("nonce-1", "nonce-1", "nonce-2")
    )

    assert first == again
    assert [trial.question for trial in first] != [trial.question for trial in other]
    assert [trial.repetition for trial in first] == sorted(trial.repetition for trial in first)
