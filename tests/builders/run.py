"""Run events."""

from typing import Final

from compass_bench.domain.ids import EndpointId
from compass_bench.domain.ledger import TransportError
from compass_bench.domain.run import CircuitOpened, RecordedEvent, RunEventKind, RunResumed, RunStarted

# started at $1, endpoint `first` opened, resumed at $2, then endpoint `second` opened
RESUMED_AFTER_A_CIRCUIT: Final = (
    RecordedEvent(seq=0, event=RunStarted(kind=RunEventKind.STARTED, budget_usd=1.0)),
    RecordedEvent(
        seq=1,
        event=CircuitOpened(
            kind=RunEventKind.CIRCUIT_OPENED, endpoint=EndpointId("first"), error=TransportError.UNAUTHORIZED
        ),
    ),
    RecordedEvent(seq=2, event=RunResumed(kind=RunEventKind.RESUMED, budget_usd=2.0)),
    RecordedEvent(
        seq=3,
        event=CircuitOpened(
            kind=RunEventKind.CIRCUIT_OPENED, endpoint=EndpointId("second"), error=TransportError.PAYMENT_REQUIRED
        ),
    ),
)
