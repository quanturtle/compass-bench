"""The ledger stores the port contract tests run against, and a fresh run to store in them.

The Postgres store runs only when COMPASS_BENCH_TEST_DATABASE_URL names a database the tests may write to.
"""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

import pytest
import sqlalchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from compass_bench.adapters.postgres.connection import create_engine, driver_arguments, upgrade_to_head
from compass_bench.adapters.postgres.ledger_store import PostgresLedgerStore, lock_key
from compass_bench.adapters.postgres.schema import metadata
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import AnswerType, ExperimentSpec, experiment_hash
from compass_bench.domain.design.schedule import Trial, build_schedule
from compass_bench.domain.ids import EndpointId, ModelId, RunId, run_id
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.run import NewRun
from compass_bench.ports.ledger_store import LedgerStore
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec, build_spec
from tests.builders.fakes import FakeLedgerStore
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis

TEST_DATABASE_VARIABLE: Final = "COMPASS_BENCH_TEST_DATABASE_URL"
NEEDS_POSTGRES: Final = pytest.mark.skipif(
    not os.environ.get(TEST_DATABASE_VARIABLE), reason=f"{TEST_DATABASE_VARIABLE} unset"
)
STORE_KINDS: Final = ("fake", pytest.param("postgres", marks=NEEDS_POSTGRES))
# a terminated session lets go of its locks a moment after pg_terminate_backend returns
LOCK_WAIT_SECONDS: Final = 5.0
LOCK_WAIT_ATTEMPTS: Final = 100
ENDPOINT: Final = EndpointSettings(
    base_url="https://openrouter.ai/api/v1",
    api_key_env="OPENROUTER_API_KEY",
    max_concurrency=2,
    timeout_seconds=30.0,
    provider_order=(),
    allow_fallbacks=True,
    require_parameters=True,
    quantizations=(),
)


@dataclass(frozen=True)
class RunInputs:
    run: NewRun
    questionnaire: Questionnaire
    spec: ExperimentSpec
    trials: tuple[Trial, ...]
    endpoints: dict[EndpointId, EndpointSettings]


def run_inputs() -> RunInputs:
    """A new run under a fresh nonce: one free-text model, 2 questions per axis, both factors, 1 repetition."""
    nonce = secrets.token_hex(8)
    questionnaire = build_questionnaire(questions_per_axis(2), FIVE_POINT_LABELS)
    models = {ModelId("model"): build_model_spec(AnswerType.FREE_TEXT)}
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS, repetitions=1))
    run = NewRun(run_id=run_id(nonce), experiment=experiment_hash(spec), nonce=nonce, code_revision="test", listings={})
    trials = build_schedule(run.run_id, spec, questionnaire, seed=0)
    return RunInputs(run, questionnaire, spec, trials, {EndpointId("openrouter"): ENDPOINT})


def schema_differences() -> list[object]:
    """What the test database, migrated to head, lacks or adds against schema.py; Alembic's own table aside."""
    url = SecretStr(os.environ[TEST_DATABASE_VARIABLE])
    upgrade_to_head(url)
    driver_url, connect_args = driver_arguments(url)
    engine = sqlalchemy.create_engine(driver_url, connect_args=connect_args)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), metadata)
    engine.dispose()
    return [difference for difference in differences if "alembic_version" not in str(difference)]


@asynccontextmanager
async def lost_lock(store: LedgerStore, run: RunId, taken_by_another: bool) -> AsyncIterator[None]:
    """End the session holding the run's lock, as a database restart does; another process may then hold it."""
    if isinstance(store, FakeLedgerStore):
        store.lose_lock(run, taken_by_another)
        yield
        store.held_elsewhere.discard(run)
        return
    assert isinstance(store, PostgresLedgerStore)
    async with store.engine.connect() as other:
        await other.execute(select(func.pg_terminate_backend(store.locks.held[run].pid)))
        await other.commit()
        if taken_by_another:
            await take_lock_when_free(other, run)
        yield
        await other.execute(select(func.pg_advisory_unlock_all()))
        await other.commit()


async def take_lock_when_free(connection: AsyncConnection, run: RunId) -> None:
    """Take the run's lock once the terminated session has let go of it, within LOCK_WAIT_SECONDS."""
    for _ in range(LOCK_WAIT_ATTEMPTS):
        if (await connection.execute(select(func.pg_try_advisory_lock(lock_key(run))))).scalar_one():
            await connection.commit()
            return
        await connection.commit()
        await asyncio.sleep(LOCK_WAIT_SECONDS / LOCK_WAIT_ATTEMPTS)
    raise AssertionError(f"run {run}'s lock was still held after {LOCK_WAIT_SECONDS} seconds")


@asynccontextmanager
async def ledger_store(kind: str) -> AsyncIterator[LedgerStore]:
    """`fake` or `postgres`; the Postgres database is migrated to head first."""
    if kind == "fake":
        yield FakeLedgerStore()
        return
    url = SecretStr(os.environ[TEST_DATABASE_VARIABLE])
    upgrade_to_head(url)
    engine = create_engine(url)
    try:
        yield PostgresLedgerStore(engine)
    finally:
        await engine.dispose()
