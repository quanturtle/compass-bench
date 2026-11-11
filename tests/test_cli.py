from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import JsonValue

from compass_bench.cli import ExitCode, PlanCommand, execute, parse_command
from compass_bench.domain.axis_pair import AxisKey
from tests.builders.instrument import FIVE_POINT_LABELS, build_question, build_questionnaire, questions_per_axis
from tests.builders.sources import (
    EXPERIMENT_PATH,
    experiment_document,
    experiment_documents,
    repeated_key_text,
    write_documents,
    wrong_type_text,
)


def test_plan_exits_ok_on_valid_inputs(tmp_path: Path) -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    write_documents(tmp_path, experiment_documents(questionnaire, models=("free",)))

    assert execute(PlanCommand(experiment=tmp_path / EXPERIMENT_PATH), {}) == ExitCode.OK


def test_plan_exits_invalid_input_on_a_repeated_question(tmp_path: Path) -> None:
    repeated = build_question("x-00", AxisKey.X)
    questionnaire = build_questionnaire((*questions_per_axis(10), repeated), FIVE_POINT_LABELS)
    write_documents(tmp_path, experiment_documents(questionnaire, models=("free",)))

    assert execute(PlanCommand(experiment=tmp_path / EXPERIMENT_PATH), {}) == ExitCode.INVALID_INPUT


@pytest.mark.parametrize("breakage", [repeated_key_text, wrong_type_text], ids=["repeated key", "wrong type"])
def test_an_invalid_experiment_file_exits_invalid_input_with_one_stderr_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], breakage: Callable[[dict[str, JsonValue]], str]
) -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    write_documents(tmp_path, experiment_documents(questionnaire, models=("free",)))
    (tmp_path / EXPERIMENT_PATH).write_text(breakage(experiment_document(("free",))))

    assert execute(PlanCommand(experiment=tmp_path / EXPERIMENT_PATH), {}) == ExitCode.INVALID_INPUT
    assert len(capsys.readouterr().err.splitlines()) == 1


@pytest.mark.parametrize("amount", ["nan", "inf", "-1"])
def test_a_budget_that_is_not_a_finite_amount_of_at_least_zero_is_refused(amount: str) -> None:
    with pytest.raises(SystemExit):
        parse_command(["run", "experiment.yaml", "--budget-usd", amount])
