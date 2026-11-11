"""Analysis end to end, on the contract's example runs."""

import asyncio

import pytest

from compass_bench.app.analyze import analyze_run
from compass_bench.contract.examples import example_endpoints, example_runs
from compass_bench.contract.v2 import report_document
from compass_bench.domain.analysis import AnalysisResult
from compass_bench.domain.axis_pair import AxisPair, Polarity
from compass_bench.domain.claims import Asserted, ClaimKind, Ordering, ReasonKind, Withheld
from tests.builders.examples import analyzed_example, store_example
from tests.builders.stores import STORE_KINDS, ledger_store


def test_the_asserted_example_places_both_models_and_orders_them_on_x_only() -> None:
    alpha, beta = analyzed_example("asserted").models
    (pair,) = analyzed_example("asserted").pairs

    assert alpha.quadrant == Asserted(kind=ClaimKind.ASSERTED, value=AxisPair(x=Polarity.POSITIVE, y=Polarity.NEGATIVE))
    assert beta.quadrant == Asserted(kind=ClaimKind.ASSERTED, value=AxisPair(x=Polarity.NEGATIVE, y=Polarity.NEGATIVE))
    assert pair.orderings.x == Asserted(kind=ClaimKind.ASSERTED, value=Ordering.FIRST_HIGHER)
    assert isinstance(pair.orderings.y, Withheld)
    assert [reason.kind for reason in pair.orderings.y.reasons] == [ReasonKind.NOT_SIGNIFICANT]


def test_the_withheld_example_crosses_0_on_x_and_misses_the_coverage_floor_on_y() -> None:
    (gamma,) = analyzed_example("withheld").models

    assert isinstance(gamma.quadrant, Withheld)
    assert [reason.kind for reason in gamma.quadrant.reasons] == [
        ReasonKind.CROSSES_MIDPOINT,
        ReasonKind.COVERAGE_BELOW_FLOOR,
    ]


def test_every_claim_of_the_partial_example_is_withheld_while_trials_are_pending() -> None:
    result = analyzed_example("partial")
    claims = [model.quadrant for model in result.models] + [
        ordering for pair in result.pairs for ordering in (pair.orderings.x, pair.orderings.y)
    ]

    assert all(isinstance(claim, Withheld) and claim.reasons[-1].kind is ReasonKind.RUN_INCOMPLETE for claim in claims)


def without_reply_times(result: AnalysisResult) -> AnalysisResult:
    """The result with each model's reply times cleared, since the store stamps results by its own clock."""
    cleared = (
        model.model_copy(update={"first_reply_at": None, "last_reply_at": None, "review_after": None})
        for model in result.models
    )
    return result.model_copy(update={"models": tuple(cleared)})


async def analyze_a_stored_example(kind: str) -> None:
    planned, _ = example_runs()["asserted"]
    async with ledger_store(kind) as store:
        run = await store_example(store, "asserted")
        stored = await store.load_run(run)
        document = await analyze_run(run, store)
    expected = without_reply_times(analyzed_example("asserted"))
    derived = document.model_copy(update={"result": without_reply_times(document.result)})
    assert derived == report_document(planned.model_copy(update={"run": stored.run}), example_endpoints(), expected)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_analyze_run_derives_the_same_document_from_a_stored_ledger(kind: str) -> None:
    asyncio.run(analyze_a_stored_example(kind))
