"""The only seed derivation. The analysis draws no random numbers, so the schedule is the only user."""

from compass_bench.domain.ids import content_hash


def schedule_seed(nonce: str) -> int:
    """Hash of the run nonce, so a run's dispatch order is fixed by its nonce."""
    return int(content_hash(["schedule", nonce]), 16)
