"""Agreement between two readers of the same items: Cohen's kappa."""

from collections import Counter
from collections.abc import Sequence


class UnpairedLabels(Exception):
    """The two readers labelled different numbers of items, so their labels are not paired."""


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Agreement beyond chance between two readers' labels of the same items, in order.

    None without items or when chance agreement is total, as when both readers use one label throughout."""
    if len(first) != len(second):
        raise UnpairedLabels(f"{len(first)} labels are paired with {len(second)}")
    if not first:
        return None
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / len(first)
    first_shares, second_shares = Counter(first), Counter(second)
    chance = sum(first_shares[label] * second_shares[label] for label in first_shares) / len(first) ** 2
    if chance == 1:
        return None
    return (observed - chance) / (1 - chance)
