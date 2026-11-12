"""Runs and their events. A run's progress is derived from the ledger and stored nowhere."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from compass_bench.domain.budget import spent_usd
from compass_bench.domain.design.experiment import ExperimentSpec
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.ids import AttemptId, EndpointId, ExperimentHash, ModelId, RunId, TrialKey
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.ledger import LedgerEntry, Orphaned, TransportError
from compass_bench.domain.listing import RunListings
from compass_bench.domain.outcome import TrialRecord, is_terminal
from compass_bench.domain.value import Value


class NewRun(Value):
    """A run as start_run writes it; the stored RunRecord adds the database's insert time.

    `listings` is what the provider listed for each model's slug when the run started."""

    run_id: RunId
    experiment: ExperimentHash
    nonce: str
    code_revision: str
    listings: RunListings


class RunRecord(Value):
    """The experiment snapshot fixes the questionnaire, so the run names only the experiment.

    `created_at` is when the database inserted the run row."""

    run_id: RunId
    experiment: ExperimentHash
    nonce: str
    code_revision: str
    listings: RunListings
    created_at: datetime


class PlannedRun(Value):
    """A run as create_run stored it: the record, both snapshots, and the trials in schedule order.

    None of it changes after the run is created; the ledger and events hold everything that does."""

    run: RunRecord
    questionnaire: Questionnaire
    spec: ExperimentSpec
    trials: tuple[Trial, ...]


class RunEventKind(StrEnum):
    STARTED = "started"
    RESUMED = "resumed"
    INTERRUPTED = "interrupted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CIRCUIT_OPENED = "circuit_opened"
    MODEL_CIRCUIT_OPENED = "model_circuit_opened"
    RETRIES_SPARED = "retries_spared"


class RunStarted(Value):
    kind: Literal[RunEventKind.STARTED]
    budget_usd: float


class RunResumed(Value):
    kind: Literal[RunEventKind.RESUMED]
    budget_usd: float


class RunInterrupted(Value):
    """Written once in-flight requests finish; a second signal ends the process before it is written."""

    kind: Literal[RunEventKind.INTERRUPTED]


class BudgetExhausted(Value):
    kind: Literal[RunEventKind.BUDGET_EXHAUSTED]
    spent_usd: float
    cap_usd: float


class CircuitOpened(Value):
    """Every model on the endpoint stops, as after a bad key."""

    kind: Literal[RunEventKind.CIRCUIT_OPENED]
    endpoint: EndpointId
    error: TransportError


class ModelCircuitOpened(Value):
    """One model stops, as when OpenRouter serves no route for its slug; the endpoint's other models continue."""

    kind: Literal[RunEventKind.MODEL_CIRCUIT_OPENED]
    model: ModelId
    error: TransportError


class RetriesSpared(Value):
    """Retryable failures of an endpoint outage: the unbroken run of them before its circuit opened, or one that
    finished while it was open. The fold counts none of `attempts` toward its trial's max_retries."""

    kind: Literal[RunEventKind.RETRIES_SPARED]
    endpoint: EndpointId
    attempts: tuple[AttemptId, ...]


type RunEvent = Annotated[
    RunStarted | RunResumed | RunInterrupted | BudgetExhausted | CircuitOpened | ModelCircuitOpened | RetriesSpared,
    Field(discriminator="kind"),
]


class RecordedEvent(Value):
    """Ordered by seq. The database stamps the event row's time, and nothing reads it back."""

    seq: int
    event: RunEvent


class CollectionEnd(StrEnum):
    """TAKEN_OVER: this process lost the run's lock, as after a database restart, and another process took it."""

    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CIRCUITS_OPEN = "circuits_open"
    TAKEN_OVER = "taken_over"


class ModelProgress(Value):
    """Every trial is finished or pending, so the model's trial count is their sum."""

    model: ModelId
    finished: int
    pending: int


class RunProgress(Value):
    models: tuple[ModelProgress, ...]
    orphaned: int
    spent_usd: float
    open_circuits: tuple[EndpointId, ...]
    open_model_circuits: tuple[ModelId, ...]


class RunOverview(Value):
    run: RunRecord
    progress: RunProgress


class NoRecordedBudget(Exception):
    """The run has no started or resumed event, so resume needs a budget argument."""


def latest_budget(events: Sequence[RecordedEvent]) -> float:
    """The budget of the latest started or resumed event; resume keeps it when no new budget is given."""
    for recorded in sorted(events, key=lambda recorded: recorded.seq, reverse=True):
        match recorded.event:
            case RunStarted(budget_usd=budget) | RunResumed(budget_usd=budget):
                return budget
    raise NoRecordedBudget("the run has never started collecting; pass --budget-usd")


def events_since_start(events: Sequence[RecordedEvent]) -> tuple[RunEvent, ...]:
    """The events after the latest started or resumed event, in seq order."""
    ordered = [recorded.event for recorded in sorted(events, key=lambda recorded: recorded.seq)]
    starts = [index for index, event in enumerate(ordered) if isinstance(event, RunStarted | RunResumed)]
    return tuple(ordered[starts[-1] + 1 :] if starts else ordered)


def open_circuits(events: Sequence[RecordedEvent]) -> tuple[EndpointId, ...]:
    """Endpoints whose circuit opened after the latest started or resumed event."""
    return tuple(sorted({event.endpoint for event in events_since_start(events) if isinstance(event, CircuitOpened)}))


def open_model_circuits(events: Sequence[RecordedEvent]) -> tuple[ModelId, ...]:
    """Models whose circuit opened after the latest started or resumed event."""
    return tuple(sorted({event.model for event in events_since_start(events) if isinstance(event, ModelCircuitOpened)}))


def spared_attempts(events: Sequence[RecordedEvent]) -> frozenset[AttemptId]:
    """Every attempt a `retries_spared` event of the run names, in any pass."""
    spared = (recorded.event for recorded in events if isinstance(recorded.event, RetriesSpared))
    return frozenset(attempt for event in spared for attempt in event.attempts)


def run_progress(
    records: Sequence[TrialRecord],
    entries: Mapping[TrialKey, Sequence[LedgerEntry]],
    events: Sequence[RecordedEvent],
) -> RunProgress:
    """An endpoint or model circuit is open when it opened after the run's latest start or resume event."""
    finished = Counter(record.trial.model for record in records if is_terminal(record.outcome))
    pending = Counter(record.trial.model for record in records if not is_terminal(record.outcome))
    every_entry = [entry for trial_entries in entries.values() for entry in trial_entries]
    return RunProgress(
        models=tuple(
            ModelProgress(model=model, finished=finished[model], pending=pending[model])
            for model in sorted({record.trial.model for record in records})
        ),
        orphaned=sum(isinstance(entry, Orphaned) for entry in every_entry),
        spent_usd=spent_usd(every_entry),
        open_circuits=open_circuits(events),
        open_model_circuits=open_model_circuits(events),
    )
