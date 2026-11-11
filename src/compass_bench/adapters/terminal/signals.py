"""Stop collection on SIGINT or SIGTERM."""

import asyncio
import signal
from typing import Final

STOP_SIGNALS: Final = (signal.SIGINT, signal.SIGTERM)


def stop_once(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    """Set `stop` and restore the default handlers, so the next signal ends the process at once."""
    stop.set()
    for signal_number in STOP_SIGNALS:
        loop.remove_signal_handler(signal_number)
    return


def install_stop(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    """The first signal sets `stop` and removes both handlers, so a second signal ends the process."""
    for signal_number in STOP_SIGNALS:
        loop.add_signal_handler(signal_number, stop_once, loop, stop)
    return
