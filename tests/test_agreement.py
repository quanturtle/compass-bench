"""Cohen's kappa, and the reader sample built from a stored run."""

import asyncio

import pytest

from compass_bench.app.reader_sample import SampleRow, SecondReading, agreement, blind, sample_replies
from compass_bench.contract.examples import DECLINE_EVERY, HEDGE_EVERY
from compass_bench.domain.reading.reading import ReadingKind
from compass_bench.domain.stats.agreement import UnpairedLabels, cohen_kappa
from tests.builders.examples import store_example
from tests.builders.fakes import FakeLedgerStore


def test_kappa_is_one_on_identical_labels_zero_at_chance_and_matches_a_hand_computed_table() -> None:
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)
    # each reader says `a` half the time, independently: observed agreement 0.5 equals chance
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)
    # 2x2 table: 20 agree on a, 5 b|a, 10 a|b, 15 agree on b
    first = ["a"] * 20 + ["a"] * 5 + ["b"] * 10 + ["b"] * 15
    second = ["a"] * 20 + ["b"] * 5 + ["a"] * 10 + ["b"] * 15
    assert cohen_kappa(first, second) == pytest.approx(0.4)


def test_kappa_is_undefined_without_items_or_when_both_readers_use_one_label() -> None:
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["a", "a"], ["a", "a"]) is None
    with pytest.raises(UnpairedLabels):
        cohen_kappa(["a"], ["a", "b"])


async def sampled_withheld() -> tuple[tuple[SampleRow, ...], tuple[SampleRow, ...]]:
    store = FakeLedgerStore()
    run = await store_example(store, "withheld")
    rows = await sample_replies((run,), store, answered=100)
    again = await sample_replies((run,), store, answered=100)
    return rows, again


def test_the_sample_holds_every_hedged_and_unanswered_reply_plus_a_seeded_draw_of_answered_ones() -> None:
    rows, again = asyncio.run(sampled_withheld())

    kinds = [row.expected.kind for row in rows]
    hedged = sum(row.expected.hedged for row in rows)
    assert kinds.count(ReadingKind.DECLINE) > 0 and hedged > 0
    assert (
        sum(kind is ReadingKind.RATING and not row.expected.hedged for kind, row in zip(kinds, rows, strict=True))
        == 100
    )
    assert [row.sample_id for row in rows] == [row.sample_id for row in again]
    assert len({row.sample_id for row in rows}) == len(rows)
    assert DECLINE_EVERY > 0 and HEDGE_EVERY > 0


def test_the_blind_copy_carries_no_reading_and_the_agreement_table_reads_the_second_readers_labels() -> None:
    rows, _ = asyncio.run(sampled_withheld())

    blinded = blind(rows)
    assert all(row.second == SecondReading(kind=None, displayed=None, hedged=None) for row in blinded)
    assert [row.sample_id for row in blinded] == [row.sample_id for row in rows]

    # a second reader who agrees with the tool on every row except one decline read as a rating
    labels = {
        row.sample_id: SecondReading(
            kind=row.expected.kind, displayed=row.expected.displayed, hedged=row.expected.hedged
        )
        for row in rows
    }
    first_decline = next(row for row in rows if row.expected.kind is ReadingKind.DECLINE)
    labels[first_decline.sample_id] = SecondReading(kind=ReadingKind.RATING, displayed=3, hedged=False)
    table = agreement(rows, labels)

    assert table.rows == len(rows) and table.unread == 0
    assert table.kind is not None and 0.9 < table.kind < 1.0
    assert table.hedged == pytest.approx(1.0) and table.displayed == pytest.approx(1.0)
    assert table.both_ratings == sum(row.expected.kind is ReadingKind.RATING for row in rows)
