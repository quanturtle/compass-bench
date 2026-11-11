"""What the provider listed about each model slug when a run started, and what that listing warns of.

A gateway accepts a sampling parameter the pinned host does not apply, so the host's own list of supported
parameters is recorded with the run. Host behaviour settles in the weeks after a model is listed, so the
listing date is recorded too.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Final

from compass_bench.domain.design.experiment import AnswerType, ExperimentSpec, ModelSpec, ReasoningEffort
from compass_bench.domain.findings import Finding, FindingCode, Severity
from compass_bench.domain.ids import ModelId
from compass_bench.domain.value import Value

# a model listed fewer than this many days before the run is warned about
FRESH_LISTING_DAYS: Final = 28
TEMPERATURE: Final = "temperature"
TOP_P: Final = "top_p"
MAX_TOKENS: Final = "max_tokens"
REASONING: Final = "reasoning"
RESPONSE_FORMAT: Final = "response_format"


class ModelListing(Value):
    """What the provider listed for a slug: when it was listed, and what the pinned host accepts.

    `host` is the host whose parameters were read, None when the endpoint pins none; `supported_parameters` is
    what that host accepts, None when the host is not among the slug's or no host was pinned."""

    listed_at: datetime | None
    host: str | None
    supported_parameters: tuple[str, ...] | None


# each model's listing, None when the provider returned none
type RunListings = Mapping[ModelId, ModelListing | None]


def sampling_parameters(model: ModelSpec) -> tuple[str, ...]:
    """The request parameters the model's settings send, named as OpenRouter lists them."""
    sampling = model.sampling
    sent = [TEMPERATURE, MAX_TOKENS]
    if sampling.top_p is not None:
        sent.append(TOP_P)
    if sampling.reasoning is not ReasoningEffort.OFF:
        sent.append(REASONING)
    if model.answer_type is AnswerType.STRUCTURED:
        sent.append(RESPONSE_FORMAT)
    return tuple(sent)


def unsupported_findings(name: ModelId, model: ModelSpec, listing: ModelListing) -> tuple[Finding, ...]:
    """A warning per sent parameter the pinned host does not list; none when its list is unknown."""
    if listing.supported_parameters is None:
        return ()
    return tuple(
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.UNSUPPORTED_PARAMETER,
            message=f"model {name!r} sends {parameter}, which host {listing.host!r} does not list as supported",
        )
        for parameter in sampling_parameters(model)
        if parameter not in listing.supported_parameters
    )


def freshness_findings(name: ModelId, listing: ModelListing, started_at: datetime) -> tuple[Finding, ...]:
    """A warning when the slug was listed fewer than FRESH_LISTING_DAYS before the run."""
    if listing.listed_at is None or started_at - listing.listed_at >= timedelta(days=FRESH_LISTING_DAYS):
        return ()
    days = (started_at - listing.listed_at).days
    return (
        Finding(
            severity=Severity.WARNING,
            code=FindingCode.FRESH_LISTING,
            message=f"model {name!r} was listed {days} days before the run; hosts settle over the first weeks",
        ),
    )


def listing_findings(spec: ExperimentSpec, listings: RunListings, started_at: datetime) -> tuple[Finding, ...]:
    """Every warning the run's listings raise, in model order; a model without a listing raises one."""
    findings: list[Finding] = []
    for name, model in spec.models.items():
        listing = listings.get(name)
        if listing is None:
            message = f"model {name!r}: the provider returned no listing for {model.model!r}"
            findings.append(Finding(severity=Severity.WARNING, code=FindingCode.NO_LISTING, message=message))
            continue
        findings.extend(unsupported_findings(name, model, listing))
        findings.extend(freshness_findings(name, listing, started_at))
    return tuple(findings)
