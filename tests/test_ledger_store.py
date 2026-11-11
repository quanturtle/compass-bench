"""The LedgerStore contract, run against the fake and, when a test database is set, against Postgres."""

import asyncio

import pytest

from compass_bench.domain.ids import attempt_id
from compass_bench.domain.ledger import Finished, LedgerEntryKind, Orphaned
from compass_bench.domain.run import RecordedEvent, RunEventKind, RunInterrupted, RunStarted
from compass_bench.ports.ledger_store import LedgerConflict, RunLocked, UnknownReference
from tests.builders.ledger import attempt_on, exchange_of, replied_result
from tests.builders.stores import (
    NEEDS_POSTGRES,
    STORE_KINDS,
    ledger_store,
    lost_lock,
    run_inputs,
    schema_differences,
)


async def create_run_twice(kind: str) -> None:
    inputs = run_inputs()
    arguments = (inputs.run, inputs.questionnaire, inputs.spec, inputs.trials, inputs.endpoints)
    async with ledger_store(kind) as store:
        first = await store.create_run(*arguments)
        again = await store.create_run(*arguments)
        planned = await store.load_run(inputs.run.run_id)
        endpoints = await store.load_endpoints(inputs.run.run_id)
    assert first == again == planned.run
    assert (planned.trials, planned.questionnaire, planned.spec) == (inputs.trials, inputs.questionnaire, inputs.spec)
    assert endpoints == inputs.endpoints


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_creating_a_run_twice_stores_it_once(kind: str) -> None:
    asyncio.run(create_run_twice(kind))


async def record_an_attempt_then_its_result(kind: str) -> None:
    inputs = run_inputs()
    trial = inputs.trials[0].key
    attempt = attempt_on(trial, 0)
    async with ledger_store(kind) as store:
        await store.create_run(inputs.run, inputs.questionnaire, inputs.spec, inputs.trials, inputs.endpoints)
        async with store.lock_run(inputs.run.run_id):
            for _ in range(2):
                await store.record_attempt(attempt, {"model": "vendor/model"})
        orphaned = await store.load_entries(inputs.run.run_id)
        for _ in range(2):
            await store.record_result(attempt_id(trial, 0), exchange_of(replied_result("4")))
        finished = await store.load_entries(inputs.run.run_id)
        with pytest.raises(LedgerConflict):
            await store.record_result(attempt_id(trial, 0), exchange_of(replied_result("5")))
    assert orphaned == {trial: (Orphaned(kind=LedgerEntryKind.ORPHANED, attempt=attempt),)}
    (entry,) = finished[trial]
    assert isinstance(entry, Finished)
    assert (entry.attempt, entry.result, entry.received_at.tzinfo is not None) == (attempt, replied_result("4"), True)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_an_attempt_is_orphaned_until_its_result_is_recorded_and_a_different_result_conflicts(kind: str) -> None:
    asyncio.run(record_an_attempt_then_its_result(kind))


async def append_events(kind: str) -> None:
    inputs = run_inputs()
    started = RecordedEvent(seq=0, event=RunStarted(kind=RunEventKind.STARTED, budget_usd=0.5))
    interrupted = RecordedEvent(seq=1, event=RunInterrupted(kind=RunEventKind.INTERRUPTED))
    async with ledger_store(kind) as store:
        await store.create_run(inputs.run, inputs.questionnaire, inputs.spec, inputs.trials, inputs.endpoints)
        for event in (started, started, interrupted):
            await store.append_event(inputs.run.run_id, event)
        with pytest.raises(LedgerConflict):
            await store.append_event(inputs.run.run_id, RecordedEvent(seq=1, event=started.event))
        events = await store.load_events(inputs.run.run_id)
    assert events == (started, interrupted)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_events_come_back_in_order_and_a_taken_seq_conflicts(kind: str) -> None:
    asyncio.run(append_events(kind))


async def lose_the_lock(kind: str) -> None:
    inputs = run_inputs()
    run = inputs.run.run_id
    first, second, third = (attempt_on(trial.key, 0) for trial in inputs.trials[:3])
    async with ledger_store(kind) as store:
        await store.create_run(inputs.run, inputs.questionnaire, inputs.spec, inputs.trials, inputs.endpoints)
        async with store.lock_run(run):
            await store.record_attempt(first, {"model": "vendor/model"})
            async with lost_lock(store, run, taken_by_another=False):
                await store.record_attempt(second, {"model": "vendor/model"})
            async with lost_lock(store, run, taken_by_another=True):
                with pytest.raises(RunLocked):
                    await store.record_attempt(third, {"model": "vendor/model"})
        entries = await store.load_entries(run)
    assert set(entries) == {first.trial, second.trial}


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_lost_lock_is_taken_again_when_free_and_another_process_holding_it_stops_attempts(kind: str) -> None:
    asyncio.run(lose_the_lock(kind))


async def write_without_parents(kind: str) -> None:
    inputs = run_inputs()
    attempt = attempt_on(inputs.trials[0].key, 0)
    async with ledger_store(kind) as store:
        with pytest.raises(UnknownReference):
            await store.record_attempt(attempt, {"model": "vendor/model"})
        with pytest.raises(UnknownReference):
            await store.record_result(attempt_id(attempt.trial, 0), exchange_of(replied_result("4")))
        with pytest.raises(UnknownReference):
            await store.append_event(
                inputs.run.run_id, RecordedEvent(seq=0, event=RunInterrupted(kind=RunEventKind.INTERRUPTED))
            )


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_an_attempt_result_or_event_whose_trial_attempt_or_run_is_missing_is_refused(kind: str) -> None:
    asyncio.run(write_without_parents(kind))


@NEEDS_POSTGRES
def test_the_migrations_build_the_schema_that_schema_py_declares() -> None:
    assert schema_differences() == []


async def lock_twice(kind: str) -> None:
    run = run_inputs().run.run_id
    async with ledger_store(kind) as store:
        async with store.lock_run(run):
            with pytest.raises(RunLocked):
                async with store.lock_run(run):
                    pass
        async with store.lock_run(run):
            pass


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_locked_run_cannot_be_locked_again_until_it_is_released(kind: str) -> None:
    asyncio.run(lock_twice(kind))
