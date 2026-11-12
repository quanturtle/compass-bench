import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Self

import httpx
import pytest
from pydantic import JsonValue
from sqlalchemy.exc import OperationalError

from compass_bench import cli
from compass_bench.app.collect import EndpointRuntime
from compass_bench.cli import (
    DbMigrateCommand,
    ExitCode,
    PlanCommand,
    RunCommand,
    RunsListCommand,
    execute,
    parse_command,
)
from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.ids import AttemptId, EndpointId
from compass_bench.ports.transport import Exchange
from compass_bench.settings import DATABASE_URL_VARIABLE
from tests.builders.fakes import FakeLedgerStore, FakeModelListings, ScriptedTransport
from tests.builders.instrument import FIVE_POINT_LABELS, build_question, build_questionnaire, questions_per_axis
from tests.builders.ledger import replied_result
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


@pytest.mark.parametrize("command", [RunsListCommand(), DbMigrateCommand()], ids=["runs list", "db migrate"])
def test_an_unreachable_database_exits_failed_with_one_stderr_line_that_omits_the_password(
    capsys: pytest.CaptureFixture[str], command: RunsListCommand | DbMigrateCommand
) -> None:
    # a socket directory that does not exist: the connection fails at once, with no network
    environ = {DATABASE_URL_VARIABLE: "postgresql://user:secret@/scratch?host=/nonexistent-socket-directory"}

    assert execute(command, environ) == ExitCode.FAILED
    error_lines = capsys.readouterr().err.splitlines()
    assert len(error_lines) == 1 and "secret" not in error_lines[0]


def test_a_database_url_with_a_port_that_is_not_a_number_exits_invalid_input_with_one_stderr_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environ = {DATABASE_URL_VARIABLE: "postgresql://user:secret@localhost:port/scratch"}

    assert execute(RunsListCommand(), environ) == ExitCode.INVALID_INPUT
    error_lines = capsys.readouterr().err.splitlines()
    assert len(error_lines) == 1 and "secret" not in error_lines[0]


class NullEngine:
    """The part of an engine a command touches when it ends."""

    async def dispose(self) -> None:
        return


class NullClient:
    """Stands in for the HTTP client, which no fake here uses. Building a real one reads the system proxy
    settings, and that call crashes in a forked test process on macOS, as the mutation tests run them."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *error: object) -> None:
        return


class FailingLedgerStore(FakeLedgerStore):
    """The fake ledger, whose every write of a result fails as a dropped connection does."""

    engine = NullEngine()

    async def record_result(self, attempt: AttemptId, exchange: Exchange) -> datetime:
        raise OperationalError("INSERT INTO attempt_results", {}, ConnectionError("server closed the connection"))


def test_a_database_error_during_collection_exits_resumable_with_one_stderr_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    write_documents(tmp_path, experiment_documents(questionnaire, models=("free",)))
    transport = ScriptedTransport((), replied_result("4"), None, None)
    endpoint = EndpointId("openrouter")
    monkeypatch.setattr(httpx, "AsyncClient", NullClient)
    monkeypatch.setattr(cli, "connect_store", lambda settings: FailingLedgerStore())
    monkeypatch.setattr(
        cli,
        "build_endpoints",
        lambda endpoints, environ, client: {endpoint: EndpointRuntime(transport=transport, slots=asyncio.Semaphore(2))},
    )
    monkeypatch.setattr(cli, "build_listings", lambda endpoints, client: {endpoint: FakeModelListings({})})
    environ = {DATABASE_URL_VARIABLE: "postgresql://user:secret@localhost/scratch"}

    code = execute(RunCommand(experiment=tmp_path / EXPERIMENT_PATH, budget_usd=1.0), environ)

    error_lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("compass-bench:")]
    assert code == ExitCode.RESUMABLE
    assert len(error_lines) == 1 and "database error" in error_lines[0] and "secret" not in error_lines[0]


@pytest.mark.parametrize("amount", ["nan", "inf", "-1"])
def test_a_budget_that_is_not_a_finite_amount_of_at_least_zero_is_refused(amount: str) -> None:
    with pytest.raises(SystemExit):
        parse_command(["run", "experiment.yaml", "--budget-usd", amount])
