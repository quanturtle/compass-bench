"""Progress events from collection (Observer)."""

from typing import Protocol

from compass_bench.domain.ids import RunId
from compass_bench.domain.ledger import Attempt
from compass_bench.domain.run import CollectionEnd, RunEvent, RunProgress
from compass_bench.ports.transport import Exchange


class RunObserver(Protocol):
    def on_run_started(self, run: RunId, progress: RunProgress) -> None: ...

    def on_attempt_sent(self, attempt: Attempt) -> None: ...

    def on_attempt_finished(self, attempt: Attempt, exchange: Exchange) -> None: ...

    def on_event(self, event: RunEvent) -> None:
        """Every run event, such as circuit_opened or budget_exhausted, as the collector records it."""
        ...

    def on_run_finished(self, end: CollectionEnd, progress: RunProgress) -> None: ...
