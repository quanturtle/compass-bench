"""The RunObserver: one log line per event, on a TTY and in logs alike."""

import logging
from typing import Final

from compass_bench.domain.ids import RunId
from compass_bench.domain.ledger import Attempt, Completed, TransportFailed
from compass_bench.domain.run import CollectionEnd, RunEvent, RunEventKind, RunProgress
from compass_bench.ports.transport import Exchange

WARNING_EVENTS: Final = frozenset(
    {RunEventKind.CIRCUIT_OPENED, RunEventKind.MODEL_CIRCUIT_OPENED, RunEventKind.BUDGET_EXHAUSTED}
)


def progress_text(progress: RunProgress) -> str:
    finished = sum(model.finished for model in progress.models)
    total = finished + sum(model.pending for model in progress.models)
    return f"{finished}/{total} trials finished, ${progress.spent_usd:.4f} spent"


def exchange_text(exchange: Exchange) -> str:
    match exchange.result:
        case Completed(reply=reply):
            return f"replied {reply.text[:40]!r} ({reply.finish})"
        case TransportFailed(error=error, http_status=status):
            return f"failed: {error}" + ("" if status is None else f" (HTTP {status})")


class LogProgress:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        return

    def on_run_started(self, run: RunId, progress: RunProgress) -> None:
        self.logger.info("run %s: %s", run, progress_text(progress))
        return

    def on_attempt_sent(self, attempt: Attempt) -> None:
        self.logger.debug("trial %s attempt %d: sent", attempt.trial[:12], attempt.seq)
        return

    def on_attempt_finished(self, attempt: Attempt, exchange: Exchange) -> None:
        self.logger.info("trial %s attempt %d: %s", attempt.trial[:12], attempt.seq, exchange_text(exchange))
        return

    def on_event(self, event: RunEvent) -> None:
        """An endpoint or model circuit opening, or the budget cap, logs as a warning; any other event as info."""
        level = logging.WARNING if event.kind in WARNING_EVENTS else logging.INFO
        self.logger.log(level, "event: %s", event.model_dump_json())
        return

    def on_run_finished(self, end: CollectionEnd, progress: RunProgress) -> None:
        self.logger.info("collection %s: %s", end, progress_text(progress))
        return
