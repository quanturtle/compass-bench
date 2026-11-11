"""Collection against the fake ledger and a scripted transport: replies, a 400, an outage, the cap, a retry, a stop."""

import asyncio

import pytest

from compass_bench.app.collect import PromptsChanged, collect, retry_delay, start_run
from compass_bench.domain.ledger import Finished, Orphaned, TransportError
from compass_bench.domain.outcome import LossReason, Lost, Pending, Replied, TrialOutcome, TrialOutcomeKind
from compass_bench.domain.run import CollectionEnd, RunEventKind
from tests.builders.collection import (
    TRIAL_COUNT,
    compiled_experiment,
    largest_reservation,
    no_listings,
    outcomes,
    runtimes,
    two_model_experiment,
)
from tests.builders.fakes import (
    FakeLedgerStore,
    ModelRoutedTransport,
    ScriptedTransport,
    SilentObserver,
    TakeoverTransport,
)
from tests.builders.ledger import attempt_on, failed_result, priced_result, replied_result


async def collect_once(
    script: ScriptedTransport, budget_usd: float
) -> tuple[CollectionEnd, list[RunEventKind], tuple[TrialOutcome, ...]]:
    store = FakeLedgerStore()
    run = (await start_run(compiled_experiment(), store, no_listings(), "nonce", "test")).run_id
    end = await collect(run, budget_usd, store, runtimes(script), SilentObserver(), asyncio.Event())
    events = [recorded.event.kind for recorded in await store.load_events(run)]
    return end, events, await outcomes(store, run)


def test_every_trial_replied_completes_the_run() -> None:
    script = ScriptedTransport((), replied_result("4"), None, None)

    end, events, trial_outcomes = asyncio.run(collect_once(script, budget_usd=1.0))

    assert (end, events) == (CollectionEnd.COMPLETE, [RunEventKind.STARTED])
    assert len(trial_outcomes) == TRIAL_COUNT and all(isinstance(outcome, Replied) for outcome in trial_outcomes)


def test_a_rejected_request_loses_one_trial_and_the_rest_continue() -> None:
    script = ScriptedTransport((failed_result(TransportError.REQUEST_REJECTED),), replied_result("4"), None, None)

    end, _, trial_outcomes = asyncio.run(collect_once(script, budget_usd=1.0))

    lost = Lost(kind=TrialOutcomeKind.LOST, loss=LossReason.REQUEST_REJECTED)
    assert end is CollectionEnd.COMPLETE
    assert [outcome for outcome in trial_outcomes if not isinstance(outcome, Replied)] == [lost]


def test_an_unauthorized_endpoint_opens_its_circuit_and_leaves_every_trial_pending() -> None:
    script = ScriptedTransport((), failed_result(TransportError.UNAUTHORIZED), None, None)

    end, events, trial_outcomes = asyncio.run(collect_once(script, budget_usd=1.0))

    assert (end, events) == (CollectionEnd.CIRCUITS_OPEN, [RunEventKind.STARTED, RunEventKind.CIRCUIT_OPENED])
    assert all(isinstance(outcome, Pending) for outcome in trial_outcomes)
    assert len(script.sent) <= 2


async def collect_with_a_missing_model() -> None:
    store = FakeLedgerStore()
    compiled = two_model_experiment(("vendor/model", "vendor/missing"))
    run = (await start_run(compiled, store, no_listings(), "nonce", "test")).run_id
    transport = ModelRoutedTransport(
        {"vendor/model": replied_result("4"), "vendor/missing": failed_result(TransportError.MODEL_NOT_FOUND)}
    )

    end = await collect(run, 1.0, store, runtimes(transport), SilentObserver(), asyncio.Event())

    trials = (await store.load_run(run)).trials
    by_model = list(zip((trial.model for trial in trials), await outcomes(store, run), strict=True))
    replied = {model for model, outcome in by_model if isinstance(outcome, Replied)}
    pending = {model for model, outcome in by_model if isinstance(outcome, Pending)}
    events = [recorded.event.kind for recorded in await store.load_events(run)]
    assert (end, replied, pending) == (CollectionEnd.CIRCUITS_OPEN, {"first"}, {"second"})
    assert events == [RunEventKind.STARTED, RunEventKind.MODEL_CIRCUIT_OPENED]
    return


def test_a_missing_model_stops_only_that_model() -> None:
    asyncio.run(collect_with_a_missing_model())


def test_the_budget_cap_stops_dispatch_before_anything_is_sent() -> None:
    script = ScriptedTransport((), replied_result("4"), None, None)

    end, events, _ = asyncio.run(collect_once(script, budget_usd=0.0))

    assert (end, events) == (CollectionEnd.BUDGET_EXHAUSTED, [RunEventKind.STARTED, RunEventKind.BUDGET_EXHAUSTED])
    assert script.sent == []


def test_a_reservation_that_does_not_fit_beside_an_open_one_waits_for_it_to_settle() -> None:
    cap = 1.5 * largest_reservation()
    script = ScriptedTransport((), priced_result("4", cost_usd=cap / 1000), None, None)

    end, _, trial_outcomes = asyncio.run(collect_once(script, budget_usd=cap))

    assert end is CollectionEnd.COMPLETE and all(isinstance(outcome, Replied) for outcome in trial_outcomes)


def test_a_timeout_is_retried_and_the_retry_decides_the_trial() -> None:
    script = ScriptedTransport((failed_result(TransportError.TIMEOUT),), replied_result("4"), None, None)

    end, _, trial_outcomes = asyncio.run(collect_once(script, budget_usd=1.0))

    assert end is CollectionEnd.COMPLETE and all(isinstance(outcome, Replied) for outcome in trial_outcomes)
    assert len(script.sent) == TRIAL_COUNT + 1


async def resume_after_a_prompt_change() -> None:
    store = FakeLedgerStore()
    run = (await start_run(compiled_experiment(), store, no_listings(), "nonce", "test")).run_id
    trial = (await store.load_run(run)).trials[0]
    async with store.lock_run(run):
        await store.record_attempt(attempt_on(trial.key, 0), {"model": "vendor/model"})
    script = ScriptedTransport((), replied_result("4"), None, None)

    with pytest.raises(PromptsChanged):
        await collect(run, 1.0, store, runtimes(script), SilentObserver(), asyncio.Event())
    assert script.sent == []
    return


def test_resume_refuses_a_run_whose_stored_prompts_the_code_renders_differently() -> None:
    asyncio.run(resume_after_a_prompt_change())


async def collect_until_taken_over() -> None:
    store = FakeLedgerStore()
    run = (await start_run(compiled_experiment(), store, no_listings(), "nonce", "test")).run_id
    transport = TakeoverTransport(replied_result("4"), store, run, after=5)

    end = await collect(run, 1.0, store, runtimes(transport), SilentObserver(), asyncio.Event())

    events = [recorded.event.kind for recorded in await store.load_events(run)]
    assert (end, events) == (CollectionEnd.TAKEN_OVER, [RunEventKind.STARTED])
    assert len(store.attempts) == len(transport.sent) <= 5 + 1
    return


def test_a_run_another_process_takes_over_sends_nothing_more_and_writes_no_events() -> None:
    asyncio.run(collect_until_taken_over())


async def interrupt_then_resume() -> None:
    store = FakeLedgerStore()
    run = (await start_run(compiled_experiment(), store, no_listings(), "nonce", "test")).run_id
    stop = asyncio.Event()
    first = ScriptedTransport((), replied_result("4"), stop, stop_after=5)
    interrupted = await collect(run, 1.0, store, runtimes(first), SilentObserver(), stop)
    second = ScriptedTransport((), replied_result("4"), None, None)
    resumed = await collect(run, 1.0, store, runtimes(second), SilentObserver(), asyncio.Event())

    entries = [entry for trial_entries in (await store.load_entries(run)).values() for entry in trial_entries]
    events = [recorded.event.kind for recorded in await store.load_events(run)]
    assert (interrupted, resumed) == (CollectionEnd.INTERRUPTED, CollectionEnd.COMPLETE)
    assert events == [RunEventKind.STARTED, RunEventKind.INTERRUPTED, RunEventKind.RESUMED]
    assert len(first.sent) + len(second.sent) == TRIAL_COUNT
    assert len(entries) == TRIAL_COUNT and all(isinstance(entry, Finished) for entry in entries)
    assert not any(isinstance(entry, Orphaned) for entry in entries)
    return


def test_an_interrupted_run_resumes_without_asking_any_trial_twice() -> None:
    asyncio.run(interrupt_then_resume())


def test_the_retry_delay_doubles_from_one_second_or_ten_after_a_rate_limit_unless_retry_after_is_longer() -> None:
    assert [retry_delay(seq, None, rate_limited=False) for seq in range(3)] == [1.0, 2.0, 4.0]
    assert [retry_delay(seq, None, rate_limited=True) for seq in range(3)] == [10.0, 20.0, 40.0]
    assert retry_delay(0, 7.0, rate_limited=False) == 7.0
    assert retry_delay(0, 7.0, rate_limited=True) == 10.0
    assert retry_delay(9, None, rate_limited=True) == 60.0
