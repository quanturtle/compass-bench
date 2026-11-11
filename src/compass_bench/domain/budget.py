"""Cost estimates and the run's budget. The collector owns the one BudgetLedger."""

import math
from collections.abc import Iterable
from typing import Final

from pydantic import NonNegativeFloat

from compass_bench.domain.elicitation.prompts import Prompt
from compass_bench.domain.ids import AttemptId, attempt_id
from compass_bench.domain.ledger import Attempt, Completed, Finished, LedgerEntry
from compass_bench.domain.value import Value

# English text averages about 4 characters per token, so 3 leans high for it; denser text, such as CJK, exceeds it
CHARACTERS_PER_TOKEN: Final = 3
MESSAGE_OVERHEAD_TOKENS: Final = 4
TOKENS_PER_PRICE_UNIT: Final = 1_000_000


class Price(Value):
    prompt_usd_per_million: NonNegativeFloat
    completion_usd_per_million: NonNegativeFloat


def estimate_prompt_tokens(prompt: Prompt) -> int:
    """Characters over CHARACTERS_PER_TOKEN, plus MESSAGE_OVERHEAD_TOKENS per message, system message included."""
    texts = [message.content for message in prompt.messages]
    if prompt.system is not None:
        texts.append(prompt.system)
    return sum(math.ceil(len(text) / CHARACTERS_PER_TOKEN) + MESSAGE_OVERHEAD_TOKENS for text in texts)


def estimate_cost(prompt: Prompt, max_tokens: int, price: Price) -> float:
    """Estimate for one attempt: estimated prompt tokens plus the full completion budget; no reply schema counted."""
    prompt_usd = estimate_prompt_tokens(prompt) * price.prompt_usd_per_million
    completion_usd = max_tokens * price.completion_usd_per_million
    return (prompt_usd + completion_usd) / TOKENS_PER_PRICE_UNIT


class BudgetLedger:
    """The one owner of the run's spend and open reservations: reserve before each send, settle after."""

    def __init__(self, cap_usd: float, spent_usd: float) -> None:
        """`spent_usd` is what the ledger already counts, from spent_usd(entries)."""
        self.cap_usd = cap_usd
        self.settled_usd = spent_usd
        self.reservations: dict[AttemptId, float] = {}
        return

    def try_reserve(self, attempt: Attempt) -> bool:
        """Hold the attempt's reserved_usd; False, holding nothing, when spent plus reserved would pass the cap."""
        if self.spent_usd + attempt.reserved_usd > self.cap_usd:
            return False
        self.reservations[attempt_id(attempt.trial, attempt.seq)] = attempt.reserved_usd
        return True

    def settle(self, attempt: AttemptId, actual_usd: float | None) -> None:
        """Replace the attempt's reservation with its actual cost; an unknown actual cost keeps the reserved amount."""
        reserved = self.reservations.pop(attempt)
        self.settled_usd += reserved if actual_usd is None else actual_usd
        return

    @property
    def spent_usd(self) -> float:
        """Settled costs plus open reservations, which count in full until they settle."""
        return self.settled_usd + sum(self.reservations.values())


def entry_cost(entry: LedgerEntry) -> float:
    """The reported cost of a completed reply, else the attempt's reservation."""
    match entry:
        case Finished(result=Completed(reply=reply)) if reply.usage.cost_usd is not None:
            return reply.usage.cost_usd
        case _:
            return entry.attempt.reserved_usd


def spent_usd(entries: Iterable[LedgerEntry]) -> float:
    """Every attempt as BudgetLedger.settle counts it; an orphan counts at the reservation stored with its attempt."""
    return sum(entry_cost(entry) for entry in entries)
