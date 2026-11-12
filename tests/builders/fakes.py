"""In-memory fakes for the ports."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Final

from pydantic import JsonValue

from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import ExperimentSpec, experiment_hash
from compass_bench.domain.design.schedule import Trial
from compass_bench.domain.ids import AttemptId, EndpointId, RunId, TrialKey, attempt_id
from compass_bench.domain.instrument.questionnaire import Questionnaire, questionnaire_hash
from compass_bench.domain.ledger import Attempt, AttemptResult, Finished, LedgerEntry, LedgerEntryKind, Orphaned
from compass_bench.domain.listing import ModelListing
from compass_bench.domain.run import (
    CollectionEnd,
    NewRun,
    PlannedRun,
    RecordedEvent,
    RunEvent,
    RunProgress,
    RunRecord,
    spared_attempts,
)
from compass_bench.ports.ledger_store import LedgerConflict, RunLocked, UnknownReference, UnknownRun, UnlockedRun
from compass_bench.ports.transport import CompletionRequest, Exchange

CREATED_AT: Final = datetime(2026, 1, 1, tzinfo=UTC)


def conflicts[K, V](table: dict[K, V], key: K, value: V) -> bool:
    return key in table and table[key] != value


def store_once[K, V](table: dict[K, V], key: K, value: V) -> None:
    """The Postgres insert rule: a repeated row is a no-op, and a different row under a taken key conflicts."""
    if conflicts(table, key, value):
        raise LedgerConflict(f"a different row is stored under {key}")
    table.setdefault(key, value)
    return


class FakeLedgerStore:
    """LedgerStore in memory with the Postgres store's conflict rules; it stamps every run at CREATED_AT."""

    def __init__(self) -> None:
        self.questionnaires: dict[str, Questionnaire] = {}
        self.experiments: dict[str, ExperimentSpec] = {}
        self.runs: dict[RunId, tuple[NewRun, dict[EndpointId, EndpointSettings]]] = {}
        self.trials: dict[RunId, tuple[Trial, ...]] = {}
        self.attempts: dict[AttemptId, tuple[Attempt, dict[str, JsonValue]]] = {}
        self.results: dict[AttemptId, tuple[AttemptResult, bytes | None, int, datetime]] = {}
        self.events: dict[RunId, dict[int, RunEvent]] = {}
        # runs this process locked; runs whose lock session ended, as a restart ends it; runs another process holds
        self.locked: set[RunId] = set()
        self.lost: set[RunId] = set()
        self.held_elsewhere: set[RunId] = set()
        return

    def lose_lock(self, run: RunId, taken_by_another: bool) -> None:
        """End the session holding the run's lock, as a database restart does, and let another process take it."""
        self.locked.discard(run)
        self.lost.add(run)
        if taken_by_another:
            self.held_elsewhere.add(run)
        return

    def run_of(self, trial: TrialKey) -> RunId:
        """The trial's run; the attempt's trial must be stored, as the Postgres foreign key requires."""
        for run, trials in self.trials.items():
            if any(stored.key == trial for stored in trials):
                return run
        raise UnknownReference(f"attempts: no trial {trial}")

    def record(self, run: RunId) -> RunRecord:
        if run not in self.runs:
            raise UnknownRun(f"no run {run}")
        new_run, _ = self.runs[run]
        return RunRecord(**new_run.model_dump(), created_at=CREATED_AT)

    async def create_run(
        self,
        run: NewRun,
        questionnaire: Questionnaire,
        spec: ExperimentSpec,
        trials: Sequence[Trial],
        endpoints: Mapping[EndpointId, EndpointSettings],
    ) -> RunRecord:
        """All or nothing, as the Postgres transaction is: a conflict on any row stores none of them."""
        if (
            conflicts(self.questionnaires, questionnaire_hash(questionnaire), questionnaire)
            or conflicts(self.experiments, experiment_hash(spec), spec)
            or conflicts(self.runs, run.run_id, (run, dict(endpoints)))
            or conflicts(self.trials, run.run_id, tuple(trials))
        ):
            raise LedgerConflict(f"run {run.run_id} conflicts with a stored row")
        store_once(self.questionnaires, questionnaire_hash(questionnaire), questionnaire)
        store_once(self.experiments, experiment_hash(spec), spec)
        store_once(self.runs, run.run_id, (run, dict(endpoints)))
        store_once(self.trials, run.run_id, tuple(trials))
        return self.record(run.run_id)

    async def load_run(self, run: RunId) -> PlannedRun:
        record = self.record(run)
        spec = self.experiments[record.experiment]
        return PlannedRun(
            run=record,
            questionnaire=self.questionnaires[spec.questionnaire],
            spec=spec,
            trials=tuple(sorted(self.trials[run], key=lambda trial: trial.position)),
        )

    async def load_endpoints(self, run: RunId) -> Mapping[EndpointId, EndpointSettings]:
        self.record(run)
        return self.runs[run][1]

    async def list_runs(self) -> tuple[RunRecord, ...]:
        return tuple(self.record(run) for run in sorted(self.runs))

    async def record_attempt(self, attempt: Attempt, payload: Mapping[str, JsonValue]) -> None:
        """Only under the run's lock: a lost lock is taken again when free, and RunLocked when another holds it."""
        run = self.run_of(attempt.trial)
        if run in self.lost and run in self.held_elsewhere:
            raise RunLocked(f"another process took run {run} after this process lost its lock")
        if run in self.lost:
            self.lost.discard(run)
            self.locked.add(run)
        if run not in self.locked:
            raise UnlockedRun(f"run {run} is not locked by this process")
        store_once(self.attempts, attempt_id(attempt.trial, attempt.seq), (attempt, dict(payload)))
        return

    async def record_result(self, attempt: AttemptId, exchange: Exchange) -> datetime:
        """The attempt must be recorded first, as the Postgres foreign key requires; results are stamped CREATED_AT."""
        if attempt not in self.attempts:
            raise UnknownReference(f"attempt_results: no attempt {attempt}")
        row = (exchange.result, exchange.raw_body, exchange.normalizer_version, CREATED_AT)
        store_once(self.results, attempt, row)
        return self.results[attempt][3]

    def entry(self, key: AttemptId, attempt: Attempt, spared: frozenset[AttemptId]) -> LedgerEntry:
        if key not in self.results:
            return Orphaned(kind=LedgerEntryKind.ORPHANED, attempt=attempt)
        result, _, _, received_at = self.results[key]
        return Finished(
            kind=LedgerEntryKind.FINISHED,
            attempt=attempt,
            result=result,
            received_at=received_at,
            in_outage=key in spared,
        )

    async def load_entries(self, run: RunId) -> Mapping[TrialKey, tuple[LedgerEntry, ...]]:
        spared = spared_attempts(await self.load_events(run))
        keys = {trial.key for trial in self.trials.get(run, ())}
        recorded = sorted(
            ((key, attempt) for key, (attempt, _) in self.attempts.items() if attempt.trial in keys),
            key=lambda pair: (pair[1].trial, pair[1].seq),
        )
        grouped: dict[TrialKey, tuple[LedgerEntry, ...]] = {}
        for key, attempt in recorded:
            grouped[attempt.trial] = (*grouped.get(attempt.trial, ()), self.entry(key, attempt, spared))
        return grouped

    async def append_event(self, run: RunId, event: RecordedEvent) -> None:
        """The run must be stored, as the Postgres foreign key requires."""
        if run not in self.runs:
            raise UnknownReference(f"run_events: no run {run}")
        store_once(self.events.setdefault(run, {}), event.seq, event.event)
        return

    async def load_events(self, run: RunId) -> tuple[RecordedEvent, ...]:
        events = self.events.get(run, {})
        return tuple(RecordedEvent(seq=seq, event=events[seq]) for seq in sorted(events))

    @asynccontextmanager
    async def lock_run(self, run: RunId) -> AsyncIterator[None]:
        if run in self.locked or run in self.held_elsewhere:
            raise RunLocked(f"another process is collecting run {run}")
        self.locked.add(run)
        try:
            yield
        finally:
            self.locked.discard(run)
            self.lost.discard(run)


class ScriptedTransport:
    """Answers each send with the next scripted result, then with `default`; `stop` is set on send `stop_after`."""

    def __init__(
        self,
        script: Sequence[AttemptResult],
        default: AttemptResult,
        stop: asyncio.Event | None,
        stop_after: int | None,
    ) -> None:
        self.script = list(script)
        self.default = default
        self.stop = stop
        self.stop_after = stop_after
        self.sent: list[dict[str, JsonValue]] = []
        return

    def payload(self, request: CompletionRequest) -> dict[str, JsonValue]:
        return {"model": request.model, "prompt": request.prompt.model_dump(mode="json")}

    async def send(self, payload: dict[str, JsonValue]) -> Exchange:
        self.sent.append(payload)
        if self.stop is not None and len(self.sent) == self.stop_after:
            self.stop.set()
        # yield to the event loop, as a real request does, so concurrent workers interleave
        await asyncio.sleep(0)
        result = self.script.pop(0) if self.script else self.default
        return Exchange(result=result, raw_body=b'{"id": "scripted"}', normalizer_version=1, retry_after_seconds=None)


class TakeoverTransport:
    """Answers every send with `result`; on send `after`, the store loses the run's lock to another process."""

    def __init__(self, result: AttemptResult, store: FakeLedgerStore, run: RunId, after: int) -> None:
        self.result = result
        self.store = store
        self.run = run
        self.after = after
        self.sent: list[dict[str, JsonValue]] = []
        return

    def payload(self, request: CompletionRequest) -> dict[str, JsonValue]:
        return {"model": request.model, "prompt": request.prompt.model_dump(mode="json")}

    async def send(self, payload: dict[str, JsonValue]) -> Exchange:
        self.sent.append(payload)
        if len(self.sent) == self.after:
            self.store.lose_lock(self.run, taken_by_another=True)
        await asyncio.sleep(0)
        return Exchange(result=self.result, raw_body=b'{"id": "taken"}', normalizer_version=1, retry_after_seconds=None)


class ModelRoutedTransport:
    """Answers each send with the result scripted for the payload's model slug."""

    def __init__(self, results: Mapping[str, AttemptResult]) -> None:
        self.results = results
        self.sent: list[dict[str, JsonValue]] = []
        return

    def payload(self, request: CompletionRequest) -> dict[str, JsonValue]:
        return {"model": request.model, "prompt": request.prompt.model_dump(mode="json")}

    async def send(self, payload: dict[str, JsonValue]) -> Exchange:
        self.sent.append(payload)
        await asyncio.sleep(0)
        result = self.results[str(payload["model"])]
        return Exchange(result=result, raw_body=b'{"id": "routed"}', normalizer_version=1, retry_after_seconds=None)


class FakeModelListings:
    """Answers each slug with its scripted listing, or None for a slug not scripted; the host asked for is kept."""

    def __init__(self, listings: Mapping[str, ModelListing]) -> None:
        self.listings = listings
        self.asked: list[tuple[str, str | None]] = []
        return

    async def listing(self, slug: str, host: str | None) -> ModelListing | None:
        self.asked.append((slug, host))
        listing = self.listings.get(slug)
        return listing if listing is None else listing.model_copy(update={"host": host})


class SilentObserver:
    """A RunObserver that records nothing."""

    def on_run_started(self, run: RunId, progress: RunProgress) -> None:
        return

    def on_attempt_sent(self, attempt: Attempt) -> None:
        return

    def on_attempt_finished(self, attempt: Attempt, exchange: Exchange) -> None:
        return

    def on_event(self, event: RunEvent) -> None:
        return

    def on_run_finished(self, end: CollectionEnd, progress: RunProgress) -> None:
        return
