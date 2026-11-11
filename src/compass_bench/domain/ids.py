"""Domain identifiers and the deterministic keys derived from them."""

import hashlib
import json
from typing import Final, NewType

from pydantic import JsonValue

from compass_bench.domain.axis_pair import Polarity

QuestionId = NewType("QuestionId", str)
ModelId = NewType("ModelId", str)
EndpointId = NewType("EndpointId", str)
ConditionId = NewType("ConditionId", str)
TrialKey = NewType("TrialKey", str)
AttemptId = NewType("AttemptId", str)
RunId = NewType("RunId", str)
QuestionnaireHash = NewType("QuestionnaireHash", str)
ExperimentHash = NewType("ExperimentHash", str)
PoolId = NewType("PoolId", str)

RUN_ID_LENGTH: Final = 12


def content_hash(document: JsonValue) -> str:
    """SHA-256 of the canonical JSON form: sorted keys, no insignificant whitespace."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_id(nonce: str) -> RunId:
    """Derived from the run nonce, so a run draws one random value; 12 hex digits, short enough to type."""
    return RunId(content_hash(["run", nonce])[:RUN_ID_LENGTH])


def trial_key(
    run: RunId, model: ModelId, question: QuestionId, polarity: Polarity, condition: ConditionId, repetition: int
) -> TrialKey:
    """Key a trial by everything that makes it distinct, so re-creating a run's trials is idempotent."""
    return TrialKey(content_hash(["trial", run, model, question, int(polarity), condition, repetition]))


def attempt_id(trial: TrialKey, seq: int) -> AttemptId:
    return AttemptId(content_hash(["attempt", trial, seq]))
