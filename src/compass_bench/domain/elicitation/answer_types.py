"""Answer types (Strategy): the reply schema each sends beside the prompt, and the rules each reads replies with.

The prompt is the same for every answer type; an answer type changes only the request's generation parameters."""

from typing import Protocol

from pydantic import JsonValue

from compass_bench.domain.design.conditions import Condition
from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.elicitation.prompts import rating_schema
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.ledger import Reply
from compass_bench.domain.reading.free_text import FREE_TEXT_RULES
from compass_bench.domain.reading.reading import ReadContext, Reading, first_decision
from compass_bench.domain.reading.structured import STRUCTURED_RULES


class AnswerTypeStrategy(Protocol):
    def reply_schema(self, scale: Scale, condition: Condition) -> dict[str, JsonValue] | None: ...

    def read(self, reply: Reply, context: ReadContext) -> Reading: ...


class FreeTextRating:
    """Send no reply schema; read the reply with the free-text rules."""

    def reply_schema(self, scale: Scale, condition: Condition) -> dict[str, JsonValue] | None:
        return None

    def read(self, reply: Reply, context: ReadContext) -> Reading:
        return first_decision(FREE_TEXT_RULES, reply, context)


class StructuredRating:
    """Send a strict schema for a JSON object with a root `rating`; read only that member, with no digit fallback."""

    def reply_schema(self, scale: Scale, condition: Condition) -> dict[str, JsonValue] | None:
        return rating_schema(scale, condition)

    def read(self, reply: Reply, context: ReadContext) -> Reading:
        return first_decision(STRUCTURED_RULES, reply, context)


def answer_type_strategy(answer_type: AnswerType) -> AnswerTypeStrategy:
    match answer_type:
        case AnswerType.FREE_TEXT:
            return FreeTextRating()
        case AnswerType.STRUCTURED:
            return StructuredRating()
