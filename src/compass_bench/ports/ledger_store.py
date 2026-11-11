"""The append-only ledger. Every write is idempotent on its natural key.

Repeating a stored ledger row is a no-op; writing a different row under a taken key raises LedgerConflict.
While the database is unreachable, a write waits and retries, so collection pauses instead of losing a reply.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue

from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import ExperimentSpec
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.ids import AttemptId, EndpointId, RunId, TrialKey
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.ledger import Attempt, LedgerEntry
from compass_bench.domain.run import NewRun, PlannedRun, RecordedEvent, RunRecord
from compass_bench.ports.transport import Exchange


class RunLocked(Exception):
    """Another process owns the run."""


class UnlockedRun(Exception):
    """An attempt was recorded for a run this process has not locked."""


class LedgerConflict(Exception):
    """A different row is already stored under the key, such as another event at a taken run_events seq."""


class UnknownRun(Exception):
    """No run is stored under the id."""


class UnknownReference(Exception):
    """A row names a run, trial, or attempt the ledger does not hold, such as a result for an unrecorded attempt."""


class LedgerStore(Protocol):
    async def create_run(
        self,
        run: NewRun,
        questionnaire: Questionnaire,
        spec: ExperimentSpec,
        trials: Sequence[Trial],
        endpoints: Mapping[EndpointId, EndpointSettings],
    ) -> RunRecord:
        """Write both snapshots, the run, and every trial in one transaction, and return the stored run.

        Endpoint settings are stored so resume needs no catalog; they name key variables, never keys."""
        ...

    async def load_run(self, run: RunId) -> PlannedRun:
        """The run with both snapshots and its trials, everything create_run wrote except the endpoints."""
        ...

    async def load_endpoints(self, run: RunId) -> Mapping[EndpointId, EndpointSettings]: ...

    async def list_runs(self) -> tuple[RunRecord, ...]: ...

    async def record_attempt(self, attempt: Attempt, payload: Mapping[str, JsonValue]) -> None:
        """Committed before the request is sent, and only while this process holds the run's lock.

        A lock whose session ended is taken again; RunLocked means another process took it meanwhile."""
        ...

    async def record_result(self, attempt: AttemptId, exchange: Exchange) -> datetime:
        """Store the result and return when the ledger recorded it; a repeated result returns the first time."""
        ...

    async def load_entries(self, run: RunId) -> Mapping[TrialKey, tuple[LedgerEntry, ...]]: ...

    async def append_event(self, run: RunId, event: RecordedEvent) -> None: ...

    async def load_events(self, run: RunId) -> tuple[RecordedEvent, ...]: ...

    def lock_run(self, run: RunId) -> AbstractAsyncContextManager[None]:
        """Hold the run's single-owner lock; raises RunLocked when another process holds it.

        record_attempt checks the lock, so a process that lost it sends nothing more."""
        ...
