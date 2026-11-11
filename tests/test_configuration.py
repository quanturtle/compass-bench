"""The elicitation each model is asked under, compared across the models of one experiment."""

from compass_bench.domain.design.configuration import (
    ElicitationDifference,
    PairElicitation,
    elicitation_findings,
    pair_elicitations,
)
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import AnswerType, ModelSpec, ReasoningEffort
from compass_bench.domain.findings import FindingCode, Severity
from compass_bench.domain.ids import EndpointId, ModelId
from tests.builders.design import build_model_spec
from tests.builders.stores import ENDPOINT

OPENROUTER = EndpointId("openrouter")
PINNED = EndpointId("pinned")
DIRECT = ModelId("direct")
REASONING = ModelId("reasoning")


def reasoning_model() -> ModelSpec:
    """A model on a pinned fp8 host that answers after a low reasoning effort within 512 tokens."""
    direct = build_model_spec(AnswerType.FREE_TEXT)
    sampling = direct.sampling.model_copy(update={"max_tokens": 512, "reasoning": ReasoningEffort.LOW})
    return direct.model_copy(update={"endpoint": PINNED, "sampling": sampling})


def pinned_endpoint() -> EndpointSettings:
    return ENDPOINT.model_copy(update={"provider_order": ("deepinfra/fp8",), "quantizations": ("fp8",)})


def test_two_models_asked_alike_share_their_elicitation() -> None:
    models = {DIRECT: build_model_spec(AnswerType.FREE_TEXT), ModelId("twin"): build_model_spec(AnswerType.FREE_TEXT)}

    (pair,) = pair_elicitations(models, {OPENROUTER: ENDPOINT})

    assert pair == PairElicitation(first=DIRECT, second=ModelId("twin"), differs=())
    assert elicitation_findings(models, {OPENROUTER: ENDPOINT}) == ()


def test_each_field_on_which_two_models_differ_is_named_with_both_values() -> None:
    models = {REASONING: reasoning_model(), DIRECT: build_model_spec(AnswerType.STRUCTURED)}
    endpoints = {OPENROUTER: ENDPOINT, PINNED: pinned_endpoint()}

    (pair,) = pair_elicitations(models, endpoints)

    assert (pair.first, pair.second) == (DIRECT, REASONING)
    assert pair.differs == (
        ElicitationDifference(field="answer_type", first="structured", second="free_text"),
        ElicitationDifference(field="max_tokens", first="8", second="512"),
        ElicitationDifference(field="reasoning", first="off", second="low"),
        ElicitationDifference(field="provider_order", first="any host", second="deepinfra/fp8"),
        ElicitationDifference(field="quantizations", first="any precision", second="fp8"),
    )


def test_the_plan_warns_once_per_field_that_differs_across_the_models() -> None:
    models = {REASONING: reasoning_model(), DIRECT: build_model_spec(AnswerType.FREE_TEXT)}

    findings = elicitation_findings(models, {OPENROUTER: ENDPOINT, PINNED: pinned_endpoint()})

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.WARNING, FindingCode.MIXED_ELICITATIONS)
    ] * 4
    assert findings[1].message == (
        "reasoning differs across the models (reasoning low, direct off), so their pairs compare elicitations"
    )


def test_an_unknown_endpoint_leaves_the_routing_fields_out_of_the_comparison() -> None:
    models = {REASONING: reasoning_model(), DIRECT: build_model_spec(AnswerType.FREE_TEXT)}

    (pair,) = pair_elicitations(models, {OPENROUTER: ENDPOINT})

    assert [difference.field for difference in pair.differs] == ["max_tokens", "reasoning"]
