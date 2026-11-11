"""The elicitation a model is asked under, and whether two models of one experiment share it.

A configuration is a served model behind an endpoint with its answer type, sampling, reasoning effort, pinned host,
and precision filter. Two models of one run that differ in any of these are compared as two elicitations, and the
report says so beside their pair; a reasoning endpoint answers after a hidden chain a direct endpoint has none of.
"""

from collections.abc import Mapping
from itertools import combinations
from typing import Final

from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import ModelSpec
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import EndpointId, ModelId
from compass_bench.domain.value import Value

# the fields of a configuration that change how a model is asked, in the order the report names them
ELICITATION_FIELDS: Final = (
    "answer_type",
    "temperature",
    "top_p",
    "max_tokens",
    "reasoning",
    "provider_order",
    "quantizations",
)


class ElicitationDifference(Value):
    """One field of the elicitation on which two models differ, with each model's value as the report prints it."""

    field: str
    first: str
    second: str


class PairElicitation(Value):
    """Two models of an experiment, in canonical model-id order, and the elicitation fields on which they differ;
    an empty `differs` means the pair shares its elicitation."""

    first: ModelId
    second: ModelId
    differs: tuple[ElicitationDifference, ...]


def listed_text(values: tuple[str, ...], when_empty: str) -> str:
    return ", ".join(values) or when_empty


def elicitation(model: ModelSpec, endpoint: EndpointSettings | None) -> dict[str, str]:
    """Each elicitation field's value as text; the endpoint fields are left out when the endpoint is unknown."""
    sampling = model.sampling
    fields = {
        "answer_type": str(model.answer_type),
        "temperature": str(sampling.temperature),
        "top_p": "host default" if sampling.top_p is None else str(sampling.top_p),
        "max_tokens": str(sampling.max_tokens),
        "reasoning": str(sampling.reasoning),
    }
    if endpoint is not None:
        fields["provider_order"] = listed_text(endpoint.provider_order, "any host")
        fields["quantizations"] = listed_text(endpoint.quantizations, "any precision")
    return fields


def pair_elicitations(
    models: Mapping[ModelId, ModelSpec], endpoints: Mapping[EndpointId, EndpointSettings]
) -> tuple[PairElicitation, ...]:
    """Every pair of the models in canonical order, each with the fields on which its two elicitations differ."""
    elicitations = {name: elicitation(model, endpoints.get(model.endpoint)) for name, model in models.items()}
    return tuple(
        PairElicitation(
            first=first,
            second=second,
            differs=tuple(
                ElicitationDifference(field=field, first=elicitations[first][field], second=elicitations[second][field])
                for field in ELICITATION_FIELDS
                if field in elicitations[first]
                and field in elicitations[second]
                and elicitations[first][field] != elicitations[second][field]
            ),
        )
        for first, second in combinations(sorted(models), 2)
    )


def elicitation_findings(
    models: Mapping[ModelId, ModelSpec], endpoints: Mapping[EndpointId, EndpointSettings]
) -> tuple[Finding, ...]:
    """A warning per elicitation field on which the experiment's models differ, naming each model's value."""
    elicitations = {name: elicitation(model, endpoints.get(model.endpoint)) for name, model in models.items()}
    findings: list[Finding] = []
    for field in ELICITATION_FIELDS:
        values = {name: fields[field] for name, fields in elicitations.items() if field in fields}
        if len(set(values.values())) < 2:
            continue
        listed = ", ".join(f"{name} {value}" for name, value in values.items())
        findings.append(
            Finding(
                severity=Severity.WARNING,
                code=FindingCode.MIXED_ELICITATIONS,
                message=f"{field} differs across the models ({listed}), so their pairs compare elicitations",
            )
        )
    return tuple(findings)
