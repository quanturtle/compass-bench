"""Collection: drive pending trials through the transports into the ledger (producer-consumer)."""

import asyncio
import heapq
from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field

from compass_bench.app.compile import CompiledExperiment
from compass_bench.domain.analysis import trial_records
from compass_bench.domain.budget import BudgetLedger, estimate_cost, spent_usd
from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import (
    ExperimentSpec,
    design_conditions,
    design_prompt,
    effective_scale,
    experiment_hash,
)
from compass_bench.domain.design.schedule import Trial, build_schedule
from compass_bench.domain.elicitation.answer_types import answer_type_strategy
from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.ids import EndpointId, ModelId, RunId, TrialKey, attempt_id, run_id
from compass_bench.domain.instrument.questionnaire import Questionnaire, question_index
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.ledger import (
    Attempt,
    AttemptResult,
    Completed,
    Finished,
    LedgerEntry,
    LedgerEntryKind,
    TransportError,
    TransportFailed,
    counts_toward_circuit,
    opens_circuit,
    opens_model_circuit,
)
from compass_bench.domain.listing import ModelListing
from compass_bench.domain.outcome import fold_outcome, is_terminal
from compass_bench.domain.reading.reading import ReadContext
from compass_bench.domain.run import (
    BudgetExhausted,
    CircuitOpened,
    CollectionEnd,
    ModelCircuitOpened,
    NewRun,
    PlannedRun,
    RecordedEvent,
    RunEvent,
    RunEventKind,
    RunInterrupted,
    RunProgress,
    RunRecord,
    RunResumed,
    RunStarted,
    run_progress,
)
from compass_bench.domain.stats.seeds import schedule_seed
from compass_bench.domain.value import Value
from compass_bench.ports.ledger_store import LedgerStore, RunLocked
from compass_bench.ports.listings import ModelListings
from compass_bench.ports.run_observer import RunObserver
from compass_bench.ports.transport import CompletionRequest, Transport

CIRCUIT_FAILURE_LIMIT: Final = 5
BACKOFF_FIRST_SECONDS: Final = 1.0
# the bundled max_retries of 3 then waits 10, 20 and 40 s, 70 s in all, past a per-minute window
RATE_LIMIT_FIRST_SECONDS: Final = 10.0
BACKOFF_MAX_SECONDS: Final = 60.0
# a host's Retry-After is honoured up to five minutes, so one header cannot stall the run
RETRY_AFTER_MAX_SECONDS: Final = 300.0


class ExperimentChanged(Exception):
    """The run's stored experiment snapshot no longer hashes to the run's experiment hash."""


class PromptsChanged(Exception):
    """The installed code renders a prompt other than the one a stored attempt of the run was sent with."""


class CircuitKind(StrEnum):
    CLOSED = "closed"
    OPEN = "open"


class ClosedCircuit(Value):
    kind: Literal[CircuitKind.CLOSED]
    consecutive_failures: int


class OpenCircuit(Value):
    kind: Literal[CircuitKind.OPEN]
    error: TransportError


type Circuit = Annotated[ClosedCircuit | OpenCircuit, Field(discriminator="kind")]


class DispatchStepKind(StrEnum):
    SETTLED = "settled"
    REQUEUED = "requeued"
    UNAFFORDABLE = "unaffordable"
    TAKEN_OVER = "taken_over"


class Settled(Value):
    """The trial's outcome is terminal; `entry` is the attempt that made it so."""

    kind: Literal[DispatchStepKind.SETTLED]
    entry: Finished


class Requeued(Value):
    """Send the trial's next attempt after the longer of the backoff and Retry-After.

    No worker slot waits for it."""

    kind: Literal[DispatchStepKind.REQUEUED]
    delay_seconds: float
    entry: Finished


class Unaffordable(Value):
    """The budget could not reserve the attempt's estimated cost, so nothing was sent.

    With `reservations_open`, other attempts held reservations that may settle lower, so the trial waits and retries."""

    kind: Literal[DispatchStepKind.UNAFFORDABLE]
    reservations_open: bool


class TakenOver(Value):
    """This process lost the run's lock and another process took it, so the attempt was neither recorded nor sent."""

    kind: Literal[DispatchStepKind.TAKEN_OVER]


type DispatchStep = Annotated[Settled | Requeued | Unaffordable | TakenOver, Field(discriminator="kind")]


@dataclass(frozen=True)
class EndpointRuntime:
    """`slots` admits at most the endpoint's max_concurrency requests at once."""

    transport: Transport
    slots: asyncio.Semaphore


def pinned_host(endpoint: EndpointSettings) -> str | None:
    """The first host of the endpoint's provider order, or None when it pins none."""
    return endpoint.provider_order[0] if endpoint.provider_order else None


async def model_listings(
    compiled: CompiledExperiment, listings: Mapping[EndpointId, ModelListings]
) -> dict[ModelId, ModelListing | None]:
    """Each model's listing from its endpoint's provider, read for the host the endpoint pins."""
    return {
        name: await listings[model.endpoint].listing(model.model, pinned_host(compiled.endpoints[model.endpoint]))
        for name, model in compiled.spec.models.items()
    }


async def start_run(
    compiled: CompiledExperiment,
    ledger: LedgerStore,
    listings: Mapping[EndpointId, ModelListings],
    nonce: str,
    code_revision: str,
) -> RunRecord:
    """Read each model's listing, then write the snapshots, the run, and every trial in one create_run call,
    before any request is sent. The run id and the schedule seed derive from the nonce."""
    run = run_id(nonce)
    trials = build_schedule(run, compiled.spec, compiled.questionnaire, schedule_seed(nonce))
    new_run = NewRun(
        run_id=run,
        experiment=experiment_hash(compiled.spec),
        nonce=nonce,
        code_revision=code_revision,
        listings=await model_listings(compiled, listings),
    )
    return await ledger.create_run(new_run, compiled.questionnaire, compiled.spec, trials, compiled.endpoints)


def pending_trials(
    trials: Sequence[Trial],
    entries: Mapping[TrialKey, Sequence[LedgerEntry]],
    spec: ExperimentSpec,
    questionnaire: Questionnaire,
) -> tuple[Trial, ...]:
    """Non-terminal trials, in schedule order."""
    records = trial_records(trials, entries, questionnaire, spec)
    return tuple(record.trial for record in records if not is_terminal(record.outcome))


def trial_context(trial: Trial, spec: ExperimentSpec, questionnaire: Questionnaire) -> tuple[str, Condition, Scale]:
    """The statement the trial asks, its condition, and the scale it is asked on."""
    statement = question_index(questionnaire)[trial.question].statements.get(trial.polarity)
    condition = {condition.id: condition for condition in design_conditions(spec.design)}[trial.condition]
    return statement, condition, effective_scale(spec.design, questionnaire.scale)


def trial_prompt(trial: Trial, spec: ExperimentSpec, questionnaire: Questionnaire) -> Prompt:
    """The prompt every attempt of the trial sends; every answer type sends the same one."""
    statement, condition, scale = trial_context(trial, spec, questionnaire)
    return design_prompt(spec.design, statement, condition, scale)


def next_attempt(
    trial: Trial,
    entries: Sequence[LedgerEntry],
    spec: ExperimentSpec,
    questionnaire: Questionnaire,
) -> Attempt | None:
    """The next ask or retry for the trial, with its estimated cost; None once its outcome is terminal."""
    _, condition, scale = trial_context(trial, spec, questionnaire)
    model = spec.models[trial.model]
    if is_terminal(fold_outcome(entries, model, ReadContext(scale=scale, condition=condition), spec.design)):
        return None
    prompt = trial_prompt(trial, spec, questionnaire)
    seq = max((entry.attempt.seq for entry in entries), default=-1) + 1
    reserved = estimate_cost(prompt, model.sampling.max_tokens, model.price)
    return Attempt(trial=trial.key, seq=seq, prompt=prompt, reserved_usd=reserved)


def circuit_after(circuit: Circuit, failure: TransportError | None) -> Circuit:
    """An endpoint's circuit after one attempt: an endpoint-level error opens it, and a counted one adds to the count.

    Any other result resets the count; an open circuit stays open until the run resumes."""
    match circuit:
        case OpenCircuit():
            return circuit
        case ClosedCircuit(consecutive_failures=failures):
            if failure is not None and opens_circuit(failure):
                return OpenCircuit(kind=CircuitKind.OPEN, error=failure)
            if failure is not None and counts_toward_circuit(failure):
                if failures + 1 >= CIRCUIT_FAILURE_LIMIT:
                    return OpenCircuit(kind=CircuitKind.OPEN, error=failure)
                return ClosedCircuit(kind=CircuitKind.CLOSED, consecutive_failures=failures + 1)
            return ClosedCircuit(kind=CircuitKind.CLOSED, consecutive_failures=0)


def completion_request(
    trial: Trial, attempt: Attempt, spec: ExperimentSpec, questionnaire: Questionnaire
) -> CompletionRequest:
    _, condition, scale = trial_context(trial, spec, questionnaire)
    model = spec.models[trial.model]
    reply_schema = answer_type_strategy(model.answer_type).reply_schema(scale, condition)
    return CompletionRequest(
        model=model.model, prompt=attempt.prompt, sampling=model.sampling, reply_schema=reply_schema
    )


def actual_cost(result: AttemptResult) -> float | None:
    """The cost the provider reported for a reply; a failure reports none."""
    match result:
        case Completed(reply=reply):
            return reply.usage.cost_usd
        case TransportFailed():
            return None


def retry_delay(seq: int, retry_after_seconds: float | None, rate_limited: bool) -> float:
    """Exponential backoff from the attempt's seq, capped, or the Retry-After, capped too, when it is longer.

    A rate limit starts from a longer first delay, so the retries outlast the provider's window."""
    first = RATE_LIMIT_FIRST_SECONDS if rate_limited else BACKOFF_FIRST_SECONDS
    backoff = min(first * 2.0**seq, BACKOFF_MAX_SECONDS)
    return max(backoff, min(retry_after_seconds or 0.0, RETRY_AFTER_MAX_SECONDS))


async def dispatch_attempt(
    trial: Trial,
    entries: Sequence[LedgerEntry],
    spec: ExperimentSpec,
    questionnaire: Questionnaire,
    endpoint: EndpointRuntime,
    ledger: LedgerStore,
    budget: BudgetLedger,
    observer: RunObserver,
) -> DispatchStep:
    """Record the attempt next_attempt picks, send it, and record the result.

    A retry comes back as Requeued, and a lost run lock as TakenOver. The caller holds an endpoint slot throughout."""
    attempt = next_attempt(trial, entries, spec, questionnaire)
    if attempt is None:
        raise ValueError(f"trial {trial.key} is already terminal")
    if not budget.try_reserve(attempt):
        return Unaffordable(kind=DispatchStepKind.UNAFFORDABLE, reservations_open=bool(budget.reservations))
    key = attempt_id(trial.key, attempt.seq)
    payload = endpoint.transport.payload(completion_request(trial, attempt, spec, questionnaire))
    try:
        await ledger.record_attempt(attempt, payload)
    except RunLocked:
        budget.settle(key, actual_usd=0.0)
        return TakenOver(kind=DispatchStepKind.TAKEN_OVER)
    observer.on_attempt_sent(attempt)
    exchange = await endpoint.transport.send(payload)
    received_at = await ledger.record_result(key, exchange)
    budget.settle(key, actual_cost(exchange.result))
    observer.on_attempt_finished(attempt, exchange)

    # decide the trial's next step from its ledger with this attempt folded in
    entry = Finished(kind=LedgerEntryKind.FINISHED, attempt=attempt, result=exchange.result, received_at=received_at)
    _, condition, scale = trial_context(trial, spec, questionnaire)
    context = ReadContext(scale=scale, condition=condition)
    if is_terminal(fold_outcome((*entries, entry), spec.models[trial.model], context, spec.design)):
        return Settled(kind=DispatchStepKind.SETTLED, entry=entry)
    rate_limited = entry_failure(entry) is TransportError.RATE_LIMITED
    delay = retry_delay(attempt.seq, exchange.retry_after_seconds, rate_limited)
    return Requeued(kind=DispatchStepKind.REQUEUED, delay_seconds=delay, entry=entry)


def entry_failure(entry: Finished) -> TransportError | None:
    match entry.result:
        case TransportFailed(error=error):
            return error
        case Completed():
            return None


async def released_after[T](slots: asyncio.Semaphore, work: Coroutine[object, object, T]) -> T:
    """Await the work, then free the endpoint slot the caller acquired for it."""
    try:
        return await work
    finally:
        slots.release()


class Collector:
    """One collection pass under the run lock, and the one owner of its dispatch queues, circuits, and events.

    The BudgetLedger it holds is the one budget owner; workers reserve and settle through it."""

    def __init__(
        self,
        planned: PlannedRun,
        entries: dict[TrialKey, tuple[LedgerEntry, ...]],
        events: list[RecordedEvent],
        budget: BudgetLedger,
        ledger: LedgerStore,
        endpoints: Mapping[EndpointId, EndpointRuntime],
        observer: RunObserver,
        stop: asyncio.Event,
    ) -> None:
        self.planned = planned
        self.entries = entries
        self.events = events
        self.budget = budget
        self.ledger = ledger
        self.endpoints = endpoints
        self.observer = observer
        self.stop = stop
        # each endpoint's ready trials, a heap on schedule position so dispatch follows round order
        self.ready: dict[EndpointId, list[tuple[int, Trial]]] = {endpoint: [] for endpoint in endpoints}
        self.circuits: dict[EndpointId, Circuit] = {
            endpoint: ClosedCircuit(kind=CircuitKind.CLOSED, consecutive_failures=0) for endpoint in endpoints
        }
        # models with an open circuit; their trials stay pending while the endpoint's other models continue
        self.open_model_circuits: set[ModelId] = set()
        self.running: dict[asyncio.Task[DispatchStep], Trial] = {}
        self.delayed: dict[asyncio.Task[None], Trial] = {}
        # a reservation did not fit while others were open; launch waits until one of them settles
        self.awaiting_settlement = False
        self.exhausted = False
        # another process took the run's lock; the run's events are now its to write
        self.taken_over = False
        return

    def progress(self) -> RunProgress:
        planned = self.planned
        records = trial_records(planned.trials, self.entries, planned.questionnaire, planned.spec)
        return run_progress(records, self.entries, self.events)

    async def record_event(self, event: RunEvent) -> None:
        """Append the event at the next seq; once another process has taken the run, its events are left to it."""
        if self.taken_over:
            return
        seq = self.events[-1].seq + 1 if self.events else 0
        recorded = RecordedEvent(seq=seq, event=event)
        await self.ledger.append_event(self.planned.run.run_id, recorded)
        self.events.append(recorded)
        self.observer.on_event(event)
        return

    def endpoint_of(self, trial: Trial) -> EndpointId:
        return self.planned.spec.models[trial.model].endpoint

    def enqueue(self, trial: Trial) -> None:
        heapq.heappush(self.ready[self.endpoint_of(trial)], (trial.position, trial))
        return

    def is_dispatching(self) -> bool:
        return not self.stop.is_set() and not self.exhausted and not self.taken_over

    async def launch(self, group: asyncio.TaskGroup) -> None:
        """Start a worker for each ready trial whose endpoint has a free slot and whose circuits are closed.

        A trial whose model circuit is open leaves the queue and stays pending. Nothing starts while a refused
        reservation waits for an open one to settle."""
        planned = self.planned
        for endpoint, runtime in self.endpoints.items():
            queue = self.ready[endpoint]
            while (
                queue
                and self.is_dispatching()
                and not self.awaiting_settlement
                and self.circuits[endpoint].kind is CircuitKind.CLOSED
            ):
                if runtime.slots.locked():
                    break
                _, trial = heapq.heappop(queue)
                if trial.model in self.open_model_circuits:
                    continue
                await runtime.slots.acquire()
                work = dispatch_attempt(
                    trial,
                    self.entries.get(trial.key, ()),
                    planned.spec,
                    planned.questionnaire,
                    runtime,
                    self.ledger,
                    self.budget,
                    self.observer,
                )
                self.running[group.create_task(released_after(runtime.slots, work))] = trial
        return

    async def update_circuits(self, trial: Trial, entry: Finished) -> None:
        """Update the endpoint's circuit, and open the model's on a model-level error; each opening is an event."""
        endpoint = self.endpoint_of(trial)
        failure = entry_failure(entry)
        before = self.circuits[endpoint]
        after = circuit_after(before, failure)
        self.circuits[endpoint] = after
        if isinstance(before, ClosedCircuit) and isinstance(after, OpenCircuit):
            opened = CircuitOpened(kind=RunEventKind.CIRCUIT_OPENED, endpoint=endpoint, error=after.error)
            await self.record_event(opened)
        if failure is not None and opens_model_circuit(failure) and trial.model not in self.open_model_circuits:
            self.open_model_circuits.add(trial.model)
            model_opened = ModelCircuitOpened(kind=RunEventKind.MODEL_CIRCUIT_OPENED, model=trial.model, error=failure)
            await self.record_event(model_opened)
        return

    def is_open_for(self, trial: Trial) -> bool:
        """The trial may be sent: its endpoint's circuit and its model's circuit are both closed."""
        endpoint_closed = self.circuits[self.endpoint_of(trial)].kind is CircuitKind.CLOSED
        return endpoint_closed and trial.model not in self.open_model_circuits

    async def finish(self, task: asyncio.Task[DispatchStep], group: asyncio.TaskGroup) -> None:
        """Fold a finished worker's step into the queues, the ledger view, and the circuits.

        A refused reservation is the budget cap only when no other reservation was open when it was refused."""
        trial = self.running.pop(task)
        step = task.result()
        match step:
            case Unaffordable(reservations_open=True):
                self.enqueue(trial)
                # the open reservations may have settled already, earlier in this batch
                self.awaiting_settlement = bool(self.budget.reservations)
            case Unaffordable():
                self.exhausted = True
            case TakenOver():
                self.taken_over = True
            case Settled(entry=entry):
                self.entries[trial.key] = (*self.entries.get(trial.key, ()), entry)
                self.awaiting_settlement = False
                await self.update_circuits(trial, entry)
            case Requeued(delay_seconds=delay, entry=entry):
                self.entries[trial.key] = (*self.entries.get(trial.key, ()), entry)
                self.awaiting_settlement = False
                await self.update_circuits(trial, entry)
                if self.is_open_for(trial):
                    self.delayed[group.create_task(asyncio.sleep(delay))] = trial
        return

    async def dispatch(self, pending: Sequence[Trial]) -> None:
        """Dispatch until every trial settles, or until a stop, the budget cap, or open circuits leave the rest."""
        for trial in pending:
            self.enqueue(trial)
        async with asyncio.TaskGroup() as group:
            stop_waiter = group.create_task(self.stop.wait())
            while True:
                await self.launch(group)
                sleepers = list(self.delayed) if self.is_dispatching() else []
                if not self.running and not sleepers:
                    break
                stop_waiters = [] if stop_waiter.done() else [stop_waiter]
                waiting = [*self.running, *sleepers, *stop_waiters]
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                for sleeper in sorted(self.delayed.keys() & done, key=lambda task: self.delayed[task].position):
                    self.enqueue(self.delayed.pop(sleeper))
                for worker in sorted(self.running.keys() & done, key=lambda task: self.running[task].position):
                    await self.finish(worker, group)
            stop_waiter.cancel()
            for sleeper in self.delayed:
                sleeper.cancel()
        return

    def end(self) -> CollectionEnd:
        planned = self.planned
        if self.taken_over:
            return CollectionEnd.TAKEN_OVER
        if not pending_trials(planned.trials, self.entries, planned.spec, planned.questionnaire):
            return CollectionEnd.COMPLETE
        if self.stop.is_set():
            return CollectionEnd.INTERRUPTED
        if self.exhausted:
            return CollectionEnd.BUDGET_EXHAUSTED
        return CollectionEnd.CIRCUITS_OPEN

    async def record_end(self, end: CollectionEnd) -> None:
        """An interrupt or the budget cap gets its event; open circuits recorded theirs as they opened.

        A taken-over run gets none, since the process that took it writes its events."""
        match end:
            case CollectionEnd.INTERRUPTED:
                await self.record_event(RunInterrupted(kind=RunEventKind.INTERRUPTED))
            case CollectionEnd.BUDGET_EXHAUSTED:
                spent, cap = self.budget.spent_usd, self.budget.cap_usd
                exhausted = BudgetExhausted(kind=RunEventKind.BUDGET_EXHAUSTED, spent_usd=spent, cap_usd=cap)
                await self.record_event(exhausted)
            case CollectionEnd.COMPLETE | CollectionEnd.CIRCUITS_OPEN | CollectionEnd.TAKEN_OVER:
                pass
        return


def check_experiment(planned: PlannedRun) -> None:
    if experiment_hash(planned.spec) != planned.run.experiment:
        raise ExperimentChanged(f"run {planned.run.run_id}: the stored experiment no longer matches its hash")
    return


def check_prompts(planned: PlannedRun, entries: Mapping[TrialKey, Sequence[LedgerEntry]]) -> None:
    """Refuse to mix prompt versions in one run: every stored attempt must carry the prompt this code renders."""
    trials = {trial.key: trial for trial in planned.trials}
    changed = sum(
        entry.attempt.prompt != trial_prompt(trials[key], planned.spec, planned.questionnaire)
        for key, trial_entries in entries.items()
        for entry in trial_entries
    )
    if changed:
        raise PromptsChanged(
            f"run {planned.run.run_id}: {changed} stored attempts were sent with a prompt this code renders "
            f"differently; resume with the code that rendered them (run created under {planned.run.code_revision})"
        )
    return


async def collect(
    run: RunId,
    budget_usd: float,
    ledger: LedgerStore,
    endpoints: Mapping[EndpointId, EndpointRuntime],
    observer: RunObserver,
    stop: asyncio.Event,
) -> CollectionEnd:
    """Under the run lock: reload the plan, check its experiment hash and prompts, fold the ledger, and dispatch.

    It records `started` for a run with no events and `resumed` otherwise, each with budget_usd."""
    async with ledger.lock_run(run):
        planned = await ledger.load_run(run)
        check_experiment(planned)
        entries = dict(await ledger.load_entries(run))
        check_prompts(planned, entries)
        events = list(await ledger.load_events(run))
        spent = spent_usd(entry for trial_entries in entries.values() for entry in trial_entries)
        budget = BudgetLedger(cap_usd=budget_usd, spent_usd=spent)
        collector = Collector(planned, entries, events, budget, ledger, endpoints, observer, stop)

        # record the start, dispatch, then record how dispatch ended
        start: RunEvent = (
            RunResumed(kind=RunEventKind.RESUMED, budget_usd=budget_usd)
            if events
            else RunStarted(kind=RunEventKind.STARTED, budget_usd=budget_usd)
        )
        await collector.record_event(start)
        observer.on_run_started(run, collector.progress())
        await collector.dispatch(pending_trials(planned.trials, entries, planned.spec, planned.questionnaire))
        end = collector.end()
        await collector.record_end(end)
        observer.on_run_finished(end, collector.progress())
        return end
