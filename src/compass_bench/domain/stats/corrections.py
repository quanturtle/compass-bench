"""Multiplicity corrections: Bonferroni across the two axes for positions, Holm across every pair and axis for gaps."""

from collections.abc import Mapping


def bonferroni_level(level: float, family_size: int) -> float:
    """Per-test confidence level that gives a joint `level` across `family_size` tests."""
    return 1 - (1 - level) / family_size


def holm[K](p_values: Mapping[K, float]) -> dict[K, float]:
    """Holm step-down adjusted p-values; an untestable member stays in the family at p = 1.

    The i-th smallest p of m is multiplied by m - i + 1, capped at 1, and never falls below an earlier one."""
    ranked = sorted(p_values, key=lambda key: p_values[key])
    adjusted: dict[K, float] = {}
    running = 0.0
    for rank, key in enumerate(ranked):
        running = max(running, min(1.0, (len(ranked) - rank) * p_values[key]))
        adjusted[key] = running
    return {key: adjusted[key] for key in p_values}
