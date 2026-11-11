"""A stratified sample of stored replies for a second reader, and the agreement between the two readings.

The reader's own output defines the strata (every hedged reply, every unanswered one, and a seeded draw of
answered ones), so the agreement is conditional on its partition rather than a random-sample figure.
"""

import random
from collections.abc import Mapping, Sequence
from typing import Final

from compass_bench.contract.corpus import Expected, expected_of
from compass_bench.domain.analysis import trial_records
from compass_bench.domain.ids import RunId, TrialKey, content_hash
from compass_bench.domain.ledger import FinishReason, LedgerEntry
from compass_bench.domain.outcome import Replied, TrialRecord, first_reply
from compass_bench.domain.reading.reading import RatingRead, ReadingKind
from compass_bench.domain.run import PlannedRun
from compass_bench.domain.stats.agreement import cohen_kappa
from compass_bench.domain.value import Value
from compass_bench.ports.ledger_store import LedgerStore

SAMPLE_ID_LENGTH: Final = 12


class SampleRow(Value):
    """A stored reply with the reading the tool gave it."""

    sample_id: str
    run: RunId
    trial: TrialKey
    text: str
    finish: FinishReason
    expected: Expected


class SecondReading(Value):
    """A second reader's reading, filled in by hand: every field is None until read.

    `displayed` is the number the reply names, as shown; `hedged` whether decline wording stands beside it."""

    kind: ReadingKind | None
    displayed: int | None
    hedged: bool | None


class BlindRow(Value):
    """A sample row without the tool's reading, for the second reader."""

    sample_id: str
    text: str
    finish: FinishReason
    second: SecondReading


class AgreementTable(Value):
    """Cohen's kappa between the tool and the second reader, per category, each with the rows it rests on.

    `kind` is over the three reading kinds; `rating`, `decline`, and `failure` are each one kind against the
    rest; `hedged` and `displayed` are over the rows both read as ratings. A kappa is None where chance agreement
    is total or no row qualifies."""

    rows: int
    kind: float | None
    rating: float | None
    decline: float | None
    failure: float | None
    both_ratings: int
    hedged: float | None
    displayed: float | None
    unread: int


def sample_id(run: RunId, trial: TrialKey) -> str:
    return content_hash(["sample", run, trial])[:SAMPLE_ID_LENGTH]


def is_hedged(record: TrialRecord) -> bool:
    match record.outcome:
        case Replied(reading=RatingRead(hedge=hedge)):
            return hedge is not None
        case _:
            return False


def is_unanswered_reply(record: TrialRecord) -> bool:
    """A reply that read as a decline or a format failure; a lost or pending trial has no reply to read."""
    match record.outcome:
        case Replied(reading=RatingRead()):
            return False
        case Replied():
            return True
        case _:
            return False


def is_plain_rating(record: TrialRecord) -> bool:
    match record.outcome:
        case Replied(reading=RatingRead(hedge=None)):
            return True
        case _:
            return False


def sample_row(planned: PlannedRun, record: TrialRecord, entries: Sequence[LedgerEntry]) -> SampleRow | None:
    """The record as a sample row, or None when no completed reply exists for it."""
    reply = first_reply(entries)
    if reply is None or not isinstance(record.outcome, Replied):
        return None
    return SampleRow(
        sample_id=sample_id(planned.run.run_id, record.trial.key),
        run=planned.run.run_id,
        trial=record.trial.key,
        text=reply.text,
        finish=reply.finish,
        expected=expected_of(record.outcome.reading),
    )


async def sample_run(planned: PlannedRun, ledger: LedgerStore, answered: int) -> tuple[SampleRow, ...]:
    """Every hedged and every unanswered reply of the run, plus `answered` plain ratings drawn by the run's nonce."""
    entries = await ledger.load_entries(planned.run.run_id)
    records = trial_records(planned.trials, entries, planned.questionnaire, planned.spec)
    rows = {
        record.trial.key: row
        for record in records
        if (row := sample_row(planned, record, entries.get(record.trial.key, ()))) is not None
    }
    kept = [
        record for record in records if (is_hedged(record) or is_unanswered_reply(record)) and record.trial.key in rows
    ]
    plain = [record for record in records if is_plain_rating(record) and record.trial.key in rows]
    drawn = random.Random(content_hash(["sample", planned.run.nonce])).sample(plain, min(answered, len(plain)))
    return tuple(rows[record.trial.key] for record in kept + drawn)


async def sample_replies(runs: Sequence[RunId], ledger: LedgerStore, answered: int) -> tuple[SampleRow, ...]:
    rows: list[SampleRow] = []
    for run in runs:
        planned = await ledger.load_run(run)
        rows.extend(await sample_run(planned, ledger, answered))
    return tuple(rows)


def blind(rows: Sequence[SampleRow]) -> tuple[BlindRow, ...]:
    """The rows without the tool's reading, with an empty second reading to fill in."""
    empty = SecondReading(kind=None, displayed=None, hedged=None)
    return tuple(BlindRow(sample_id=row.sample_id, text=row.text, finish=row.finish, second=empty) for row in rows)


def one_against_rest(kind: ReadingKind, readings: Sequence[ReadingKind]) -> list[str]:
    return [str(kind) if reading is kind else "other" for reading in readings]


def agreement(rows: Sequence[SampleRow], labelled: Mapping[str, SecondReading]) -> AgreementTable:
    """`labelled` holds the second reader's readings by sample id; rows it leaves unread are counted, not compared."""
    pairs = [(row.expected, labelled[row.sample_id]) for row in rows if labelled.get(row.sample_id) is not None]
    read = [(expected, second) for expected, second in pairs if second.kind is not None]
    first_kinds = [expected.kind for expected, _ in read]
    second_kinds = [second.kind for _, second in read if second.kind is not None]
    ratings = [
        (expected, second)
        for expected, second in read
        if expected.kind is ReadingKind.RATING and second.kind is ReadingKind.RATING
    ]
    return AgreementTable(
        rows=len(rows),
        kind=cohen_kappa([str(kind) for kind in first_kinds], [str(kind) for kind in second_kinds]),
        rating=cohen_kappa(
            one_against_rest(ReadingKind.RATING, first_kinds), one_against_rest(ReadingKind.RATING, second_kinds)
        ),
        decline=cohen_kappa(
            one_against_rest(ReadingKind.DECLINE, first_kinds), one_against_rest(ReadingKind.DECLINE, second_kinds)
        ),
        failure=cohen_kappa(
            one_against_rest(ReadingKind.FORMAT_FAILURE, first_kinds),
            one_against_rest(ReadingKind.FORMAT_FAILURE, second_kinds),
        ),
        both_ratings=len(ratings),
        hedged=cohen_kappa(
            [str(expected.hedged) for expected, _ in ratings], [str(second.hedged) for _, second in ratings]
        ),
        displayed=cohen_kappa(
            [str(expected.displayed) for expected, _ in ratings], [str(second.displayed) for _, second in ratings]
        ),
        unread=len(rows) - len(read),
    )
