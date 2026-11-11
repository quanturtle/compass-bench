"""Interfaces for the transport, the store, the input files, and run progress. The application takes these as
parameters; adapters implement them.

Other seams need no interface: the database stamps every row's time, waits call asyncio.sleep directly, and cli.py
draws the run nonce and sets the stop event on a signal."""
