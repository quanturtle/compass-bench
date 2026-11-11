from compass_bench.domain.budget import BudgetLedger
from compass_bench.domain.ids import attempt_id
from tests.builders.ledger import TRIAL, build_attempt


def test_the_budget_refuses_a_reservation_past_the_cap_and_settles_to_the_actual_cost() -> None:
    budget = BudgetLedger(cap_usd=0.0025, spent_usd=0.0)
    first, second, third = (build_attempt(seq) for seq in range(3))

    assert budget.try_reserve(first) and budget.try_reserve(second)
    assert not budget.try_reserve(third)

    budget.settle(attempt_id(TRIAL, 0), actual_usd=0.0002)
    budget.settle(attempt_id(TRIAL, 1), actual_usd=None)

    assert budget.spent_usd == 0.0002 + second.reserved_usd
    assert budget.try_reserve(third)
