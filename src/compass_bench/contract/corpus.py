"""Corpus rows: a reply's text and finish with the reading it must get, shared by the tests and the reader sample."""

from compass_bench.domain.ledger import FinishReason
from compass_bench.domain.reading.reading import (
    DeclineRead,
    FormatFailure,
    FormatFailureKind,
    RatingRead,
    Reading,
    ReadingKind,
)
from compass_bench.domain.value import Value


class Expected(Value):
    """`displayed` and `hedged` are set for a rating and `failure` for a format failure."""

    kind: ReadingKind
    rule: str
    displayed: int | None
    hedged: bool
    failure: FormatFailureKind | None


class CorpusRow(Value):
    text: str
    finish: FinishReason
    expected: Expected


def expected_of(reading: Reading) -> Expected:
    match reading:
        case RatingRead():
            return Expected(
                kind=reading.kind,
                rule=reading.rule,
                displayed=reading.displayed,
                hedged=reading.hedge is not None,
                failure=None,
            )
        case DeclineRead():
            return Expected(kind=reading.kind, rule=reading.rule, displayed=None, hedged=False, failure=None)
        case FormatFailure():
            return Expected(kind=reading.kind, rule=reading.rule, displayed=None, hedged=False, failure=reading.failure)
