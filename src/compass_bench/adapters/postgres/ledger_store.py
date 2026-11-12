"""LedgerStore over the ledger tables. Every insert is ON CONFLICT DO NOTHING on its key.

A skipped insert compares the stored row with its own and raises LedgerConflict when they differ.
A write retries on a connection error until it commits; the conflict rule makes the retry safe.

JSONB columns are read as text and validated in JSON mode, because strict models reject Python lists.
"""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from psycopg.errors import ForeignKeyViolation
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import ColumnElement, RowMapping, Table, Text, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from compass_bench.adapters.postgres.schema import (
    attempt_results,
    attempts,
    experiments,
    questionnaires,
    run_events,
    runs,
    trials,
)
from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import ExperimentSpec, experiment_hash
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.ids import (
    AttemptId,
    ConditionId,
    EndpointId,
    ExperimentHash,
    ModelId,
    QuestionId,
    RunId,
    TrialKey,
    attempt_id,
)
from compass_bench.domain.instrument.questionnaire import Questionnaire, questionnaire_hash
from compass_bench.domain.ledger import (
    Attempt,
    AttemptResult,
    Finished,
    LedgerEntry,
    LedgerEntryKind,
    Orphaned,
)
from compass_bench.domain.listing import ModelListing
from compass_bench.domain.run import NewRun, PlannedRun, RecordedEvent, RunEvent, RunRecord, spared_attempts
from compass_bench.ports.ledger_store import LedgerConflict, RunLocked, UnknownReference, UnknownRun, UnlockedRun
from compass_bench.ports.transport import Exchange

WRITE_RETRY_FIRST_DELAY_SECONDS: Final = 0.5
WRITE_RETRY_MAX_DELAY_SECONDS: Final = 30.0
# Postgres binds at most 65535 parameters per statement; a trial row binds 8
TRIAL_ROWS_PER_INSERT: Final = 1000

# this session's identity; a pid alone can be reused by a later session
SESSION_IDENTITY: Final = text("SELECT pid, backend_start FROM pg_stat_activity WHERE pid = pg_backend_pid()")
# whether the session that took a run's lock still exists and holds an advisory lock; it holds no other
LOCK_HELD: Final = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks AS held JOIN pg_stat_activity AS session ON session.pid = held.pid"
    " WHERE held.locktype = 'advisory' AND held.granted AND held.pid = :pid AND session.backend_start = :started)"
)
ATTEMPT_RESULT: Final = TypeAdapter[AttemptResult](AttemptResult)
RUN_EVENT: Final = TypeAdapter[RunEvent](RunEvent)
ENDPOINTS: Final = TypeAdapter(dict[EndpointId, EndpointSettings])
LISTINGS: Final = TypeAdapter(dict[ModelId, ModelListing | None])


def trial_row(run: RunId, trial: Trial) -> dict[str, object]:
    return {
        "trial_key": trial.key,
        "run_id": run,
        "model_id": trial.model,
        "question_id": trial.question,
        "polarity": int(trial.polarity),
        "condition_id": trial.condition,
        "repetition": trial.repetition,
        "position": trial.position,
    }


def trial_from_row(row: RowMapping) -> Trial:
    return Trial(
        key=TrialKey(row["trial_key"]),
        model=ModelId(row["model_id"]),
        question=QuestionId(row["question_id"]),
        polarity=Polarity(row["polarity"]),
        condition=ConditionId(row["condition_id"]),
        repetition=row["repetition"],
        position=row["position"],
    )


def attempt_row(attempt: Attempt, payload: Mapping[str, JsonValue]) -> dict[str, object]:
    """`reserved_usd` binds as the float's exact decimal, so the stored NUMERIC reads back as the same float."""
    return {
        "attempt_id": attempt_id(attempt.trial, attempt.seq),
        "trial_key": attempt.trial,
        "seq": attempt.seq,
        "prompt": attempt.prompt.model_dump(mode="json"),
        "request": dict(payload),
        "reserved_usd": Decimal(repr(attempt.reserved_usd)),
    }


def result_row(attempt: AttemptId, exchange: Exchange) -> dict[str, object]:
    """The normalized result, the raw body's bytes, and the normalizer version; the result holds status and usage."""
    return {
        "attempt_id": attempt,
        "raw_body": exchange.raw_body,
        "result": ATTEMPT_RESULT.dump_python(exchange.result, mode="json"),
        "normalizer_version": exchange.normalizer_version,
    }


def entry_from_rows(attempt: RowMapping, result: RowMapping | None, spared: frozenset[AttemptId]) -> LedgerEntry:
    """An attempt row without a result row is an Orphaned entry; an attempt in `spared` finished in an outage."""
    recorded = Attempt(
        trial=TrialKey(attempt["trial_key"]),
        seq=attempt["seq"],
        prompt=Prompt.model_validate_json(attempt["prompt"]),
        reserved_usd=float(attempt["reserved_usd"]),
    )
    if result is None:
        return Orphaned(kind=LedgerEntryKind.ORPHANED, attempt=recorded)
    return Finished(
        kind=LedgerEntryKind.FINISHED,
        attempt=recorded,
        result=ATTEMPT_RESULT.validate_json(result["result"]),
        received_at=result["received_at"],
        in_outage=attempt_id(recorded.trial, recorded.seq) in spared,
    )


def run_record(row: RowMapping) -> RunRecord:
    """The listings column comes back decoded, so it is serialized again and validated in JSON mode."""
    return RunRecord(
        run_id=RunId(row["run_id"]),
        experiment=ExperimentHash(row["experiment_hash"]),
        nonce=row["nonce"],
        code_revision=row["code_revision"],
        listings=LISTINGS.validate_json(json.dumps(row["listings"])),
        created_at=row["created_at"],
    )


def event_row(run: RunId, recorded: RecordedEvent) -> dict[str, object]:
    """`kind` has its own column, so the detail holds the event's other fields."""
    detail = RUN_EVENT.dump_python(recorded.event, mode="json")
    return {"run_id": run, "seq": recorded.seq, "kind": detail.pop("kind"), "detail": detail}


def comparable(value: object) -> object:
    """NUMERIC reads back as Decimal and BYTEA may read back as memoryview; compare them as they were written."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return value


async def insert_once(connection: AsyncConnection, table: Table, row: Mapping[str, object], key: Sequence[str]) -> None:
    """Insert the row unless its key is taken; a taken key must already hold this row, else LedgerConflict.

    A row whose foreign key names no stored row raises UnknownReference."""
    statement = insert(table).values(dict(row)).on_conflict_do_nothing().returning(table.c[key[0]])
    try:
        inserted = (await connection.execute(statement)).first()
    except IntegrityError as error:
        if isinstance(error.orig, ForeignKeyViolation):
            raise UnknownReference(f"{table.name}: {error.orig.diag.message_detail}") from error
        raise
    if inserted is not None:
        return
    stored_query = select(*(table.c[name] for name in row)).where(*(table.c[name] == row[name] for name in key))
    stored = (await connection.execute(stored_query)).mappings().one()
    if any(comparable(stored[name]) != comparable(row[name]) for name in row):
        named_key = ", ".join(f"{name}={row[name]}" for name in key)
        raise LedgerConflict(f"{table.name} already holds a different row under {named_key}")
    return


async def insert_trials(connection: AsyncConnection, run: RunId, schedule: Sequence[Trial]) -> None:
    """Insert every trial; when some keys are taken, the run's stored trials must equal the schedule."""
    rows = [trial_row(run, trial) for trial in schedule]
    inserted = 0
    for start in range(0, len(rows), TRIAL_ROWS_PER_INSERT):
        chunk = rows[start : start + TRIAL_ROWS_PER_INSERT]
        statement = insert(trials).values(chunk).on_conflict_do_nothing().returning(trials.c.trial_key)
        inserted += len((await connection.execute(statement)).all())
    if inserted == len(rows):
        return
    stored = (await connection.execute(select(trials).where(trials.c.run_id == run))).mappings().all()
    if sorted((dict(row) for row in stored), key=lambda row: row["position"]) != rows:
        raise LedgerConflict(f"run {run} already holds a different trial schedule")
    return


async def write_run(
    connection: AsyncConnection,
    run: NewRun,
    questionnaire: Questionnaire,
    spec: ExperimentSpec,
    schedule: Sequence[Trial],
    endpoints: Mapping[EndpointId, EndpointSettings],
) -> RunRecord:
    questionnaire_row = {"hash": questionnaire_hash(questionnaire), "document": questionnaire.model_dump(mode="json")}
    await insert_once(connection, questionnaires, questionnaire_row, ["hash"])
    experiment_row = {"hash": experiment_hash(spec), "spec": spec.model_dump(mode="json")}
    await insert_once(connection, experiments, experiment_row, ["hash"])
    run_row = {
        "run_id": run.run_id,
        "experiment_hash": run.experiment,
        "nonce": run.nonce,
        "code_revision": run.code_revision,
        "endpoints": ENDPOINTS.dump_python(dict(endpoints), mode="json"),
        "listings": LISTINGS.dump_python(dict(run.listings), mode="json"),
    }
    await insert_once(connection, runs, run_row, ["run_id"])
    await insert_trials(connection, run.run_id, schedule)
    stored = (await connection.execute(select(runs).where(runs.c.run_id == run.run_id))).mappings().one()
    return run_record(stored)


@dataclass(frozen=True)
class HeldLock:
    """A run's advisory lock: the session that holds it, named by its backend pid and start time.

    A pid alone can be reused by a later session after a restart; the pair cannot."""

    connection: AsyncConnection
    pid: int
    started: datetime


@dataclass(frozen=True)
class RunLocks:
    """The run locks this process holds, the runs another process took from it, and the guard for re-taking."""

    held: dict[RunId, HeldLock]
    taken: set[RunId]
    retaking: asyncio.Lock


class LockLost(Exception):
    """The session that held the run's lock ended, as a database restart ends every session."""

    def __init__(self, run: RunId, ended: HeldLock) -> None:
        super().__init__(f"the session holding run {run}'s lock ended")
        self.run = run
        self.ended = ended
        return


def lock_key(run: RunId) -> ColumnElement[int]:
    return func.hashtextextended(run, 0)


async def take_lock(engine: AsyncEngine, run: RunId) -> HeldLock:
    """Take the run's lock on a session of its own; raises RunLocked when another session holds it."""
    connection = await engine.connect()
    if not (await connection.execute(select(func.pg_try_advisory_lock(lock_key(run))))).scalar_one():
        await connection.close()
        raise RunLocked(f"another process is collecting run {run}")
    session = (await connection.execute(SESSION_IDENTITY)).one()
    await connection.commit()
    return HeldLock(connection=connection, pid=session.pid, started=session.backend_start)


async def session_alive(held: HeldLock) -> bool:
    try:
        await held.connection.execute(select(1))
        await held.connection.commit()
    except OperationalError, InterfaceError:
        return False
    return True


async def release_lock(held: HeldLock, run: RunId) -> None:
    """Unlock the run and close its session; a session that already ended took its lock with it."""
    if await session_alive(held):
        await held.connection.execute(select(func.pg_advisory_unlock(lock_key(run))))
        await held.connection.commit()
    await held.connection.close()
    return


async def insert_attempt(
    connection: AsyncConnection, row: Mapping[str, object], trial: TrialKey, locks: RunLocks
) -> None:
    """Insert the attempt in the transaction that checks its run's lock session still holds the lock."""
    stored = (await connection.execute(select(trials.c.run_id).where(trials.c.trial_key == trial))).scalar_one_or_none()
    if stored is None:
        raise UnknownReference(f"attempts: no trial {trial}")
    run = RunId(stored)
    if run in locks.taken:
        raise RunLocked(f"another process took run {run} after this process lost its lock")
    held = locks.held.get(run)
    if held is None:
        raise UnlockedRun(f"run {run} is not locked by this process")
    if not (await connection.execute(LOCK_HELD, {"pid": held.pid, "started": held.started})).scalar_one():
        raise LockLost(run, held)
    await insert_once(connection, attempts, row, ["attempt_id"])
    return


async def insert_result(connection: AsyncConnection, row: Mapping[str, object], attempt: AttemptId) -> datetime:
    """Insert the result once and return the stored row's received_at, the first write's when it is repeated."""
    await insert_once(connection, attempt_results, row, ["attempt_id"])
    query = select(attempt_results.c.received_at).where(attempt_results.c.attempt_id == attempt)
    received: datetime = (await connection.execute(query)).scalar_one()
    return received


class PostgresLedgerStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        # record_attempt replaces a lock whose session ended, or marks its run taken by another process
        self.locks = RunLocks(held={}, taken=set(), retaking=asyncio.Lock())
        return

    async def committed[T](self, write: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        """Run the write in its own transaction, waiting out a lost connection with capped exponential backoff.

        A pool checkout that times out, as every checkout does while the database host is unreachable, waits too."""
        delay = WRITE_RETRY_FIRST_DELAY_SECONDS
        while True:
            try:
                async with self.engine.begin() as connection:
                    return await write(connection)
            except OperationalError, InterfaceError, PoolTimeout:
                await asyncio.sleep(delay)
                delay = min(delay * 2, WRITE_RETRY_MAX_DELAY_SECONDS)

    async def create_run(
        self,
        run: NewRun,
        questionnaire: Questionnaire,
        spec: ExperimentSpec,
        trials: Sequence[Trial],
        endpoints: Mapping[EndpointId, EndpointSettings],
    ) -> RunRecord:
        """One transaction: both snapshot rows, the run row, and every trial row; the run row supplies created_at.

        It runs before any request is sent, so it fails at once instead of waiting out an outage."""
        async with self.engine.begin() as connection:
            return await write_run(connection, run, questionnaire, spec, trials, endpoints)

    async def load_run(self, run: RunId) -> PlannedRun:
        """The run row joined to both snapshot rows, and its trial rows ordered by position."""
        run_query = (
            select(runs, cast(experiments.c.spec, Text).label("spec"))
            .join(experiments, runs.c.experiment_hash == experiments.c.hash)
            .where(runs.c.run_id == run)
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(run_query)).mappings().one_or_none()
            if row is None:
                raise UnknownRun(f"no run {run}")
            spec = ExperimentSpec.model_validate_json(row["spec"])
            document_query = select(cast(questionnaires.c.document, Text)).where(
                questionnaires.c.hash == spec.questionnaire
            )
            document = (await connection.execute(document_query)).scalar_one()
            trial_query = select(trials).where(trials.c.run_id == run).order_by(trials.c.position)
            trial_rows = (await connection.execute(trial_query)).mappings().all()
        return PlannedRun(
            run=run_record(row),
            questionnaire=Questionnaire.model_validate_json(document),
            spec=spec,
            trials=tuple(trial_from_row(trial) for trial in trial_rows),
        )

    async def load_endpoints(self, run: RunId) -> Mapping[EndpointId, EndpointSettings]:
        async with self.engine.connect() as connection:
            query = select(cast(runs.c.endpoints, Text)).where(runs.c.run_id == run)
            text = (await connection.execute(query)).scalar_one_or_none()
        if text is None:
            raise UnknownRun(f"no run {run}")
        return ENDPOINTS.validate_json(text)

    async def list_runs(self) -> tuple[RunRecord, ...]:
        async with self.engine.connect() as connection:
            rows = (await connection.execute(select(runs).order_by(runs.c.created_at, runs.c.run_id))).mappings().all()
        return tuple(run_record(row) for row in rows)

    async def record_attempt(self, attempt: Attempt, payload: Mapping[str, JsonValue]) -> None:
        """Committed before the request is sent, and only while this process holds the run's lock.

        A lock whose session ended is taken again; RunLocked means another process took it meanwhile."""
        row = attempt_row(attempt, payload)
        while True:
            try:
                await self.committed(lambda connection: insert_attempt(connection, row, attempt.trial, self.locks))
                return
            except LockLost as lost:
                await self.retake_lock(lost.run, lost.ended)

    async def retake_lock(self, run: RunId, ended: HeldLock) -> None:
        """Take the lock on a new session, waiting out the outage that ended the old one; once per ended session.

        When another process holds it, the run is marked taken, and every later record_attempt raises RunLocked."""
        async with self.locks.retaking:
            if self.locks.held.get(run) is not ended:
                return
            del self.locks.held[run]
            await ended.connection.close()
            delay = WRITE_RETRY_FIRST_DELAY_SECONDS
            while run not in self.locks.held:
                try:
                    self.locks.held[run] = await take_lock(self.engine, run)
                except RunLocked:
                    self.locks.taken.add(run)
                    return
                except OperationalError, InterfaceError, PoolTimeout:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, WRITE_RETRY_MAX_DELAY_SECONDS)
        return

    async def record_result(self, attempt: AttemptId, exchange: Exchange) -> datetime:
        row = result_row(attempt, exchange)
        return await self.committed(lambda connection: insert_result(connection, row, attempt))

    async def load_entries(self, run: RunId) -> Mapping[TrialKey, tuple[LedgerEntry, ...]]:
        """Each trial's attempts in seq order; the run's `retries_spared` events mark the ones in an outage."""
        spared = spared_attempts(await self.load_events(run))
        query = (
            select(
                attempts.c.trial_key,
                attempts.c.seq,
                cast(attempts.c.prompt, Text).label("prompt"),
                attempts.c.reserved_usd,
                cast(attempt_results.c.result, Text).label("result"),
                attempt_results.c.received_at,
            )
            .select_from(attempts)
            .join(trials, trials.c.trial_key == attempts.c.trial_key)
            .outerjoin(attempt_results, attempt_results.c.attempt_id == attempts.c.attempt_id)
            .where(trials.c.run_id == run)
            .order_by(attempts.c.trial_key, attempts.c.seq)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        grouped: defaultdict[TrialKey, list[LedgerEntry]] = defaultdict(list)
        for row in rows:
            result = row if row["result"] is not None else None
            grouped[TrialKey(row["trial_key"])].append(entry_from_rows(row, result, spared))
        return {key: tuple(entries) for key, entries in grouped.items()}

    async def append_event(self, run: RunId, event: RecordedEvent) -> None:
        row = event_row(run, event)
        await self.committed(lambda connection: insert_once(connection, run_events, row, ["run_id", "seq"]))
        return

    async def load_events(self, run: RunId) -> tuple[RecordedEvent, ...]:
        event = func.jsonb_build_object("kind", run_events.c.kind).op("||")(run_events.c.detail)
        query = select(run_events.c.seq, cast(event, Text).label("event")).where(run_events.c.run_id == run)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query.order_by(run_events.c.seq))).mappings().all()
        return tuple(RecordedEvent(seq=row["seq"], event=RUN_EVENT.validate_json(row["event"])) for row in rows)

    @asynccontextmanager
    async def lock_run(self, run: RunId) -> AsyncIterator[None]:
        """A session-level advisory lock keyed by the run id, held on a session of its own.

        A database restart ends the session and releases the lock; record_attempt notices and takes it again."""
        self.locks.held[run] = await take_lock(self.engine, run)
        try:
            yield
        finally:
            self.locks.taken.discard(run)
            held = self.locks.held.pop(run, None)
            if held is not None:
                await release_lock(held, run)
