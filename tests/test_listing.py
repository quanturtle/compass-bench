"""Model listings: the parameters a model sends, and the warnings a listing raises at run start."""

import asyncio
from datetime import UTC, datetime, timedelta

from compass_bench.app.collect import start_run
from compass_bench.domain.design.experiment import AnswerType, ReasoningEffort
from compass_bench.domain.findings import FindingCode
from compass_bench.domain.ids import ModelId
from compass_bench.domain.listing import FRESH_LISTING_DAYS, ModelListing, listing_findings, sampling_parameters
from tests.builders.collection import ENDPOINT_ID, compiled_experiment
from tests.builders.design import build_model_spec
from tests.builders.fakes import FakeLedgerStore, FakeModelListings
from tests.builders.stores import ENDPOINT

STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
MODEL = ModelId("model")


def listed(days_before: int, *parameters: str) -> ModelListing:
    return ModelListing(
        listed_at=STARTED_AT - timedelta(days=days_before), host="example", supported_parameters=parameters
    )


def test_the_parameters_sent_follow_the_models_settings() -> None:
    bare = build_model_spec(AnswerType.FREE_TEXT)
    full = bare.model_copy(
        update={
            "sampling": bare.sampling.model_copy(update={"top_p": 0.9, "reasoning": ReasoningEffort.LOW}),
            "answer_type": AnswerType.STRUCTURED,
        }
    )

    assert sampling_parameters(bare) == ("temperature", "max_tokens")
    assert sampling_parameters(full) == ("temperature", "max_tokens", "top_p", "reasoning", "response_format")


def test_a_sent_parameter_the_host_does_not_list_and_a_fresh_listing_are_warned_about() -> None:
    spec = compiled_experiment().spec

    findings = listing_findings(spec, {MODEL: listed(FRESH_LISTING_DAYS - 1, "temperature")}, STARTED_AT)

    assert [finding.code for finding in findings] == [FindingCode.UNSUPPORTED_PARAMETER, FindingCode.FRESH_LISTING]
    assert "max_tokens" in findings[0].message and f"{FRESH_LISTING_DAYS - 1} days" in findings[1].message


def test_a_settled_listing_that_lists_every_sent_parameter_raises_nothing() -> None:
    spec = compiled_experiment().spec

    assert listing_findings(spec, {MODEL: listed(FRESH_LISTING_DAYS, "temperature", "max_tokens")}, STARTED_AT) == ()


def test_a_missing_listing_or_an_unknown_parameter_list_warns_only_about_the_listing() -> None:
    spec = compiled_experiment().spec
    unknown = ModelListing(listed_at=None, host=None, supported_parameters=None)

    assert [finding.code for finding in listing_findings(spec, {}, STARTED_AT)] == [FindingCode.NO_LISTING]
    assert listing_findings(spec, {MODEL: unknown}, STARTED_AT) == ()


async def start_with_listings() -> tuple[FakeModelListings, FakeLedgerStore]:
    compiled = compiled_experiment()
    pinned = compiled.model_copy(
        update={"endpoints": {ENDPOINT_ID: ENDPOINT.model_copy(update={"provider_order": ("Pinned",)})}}
    )
    listings = FakeModelListings({"vendor/model": listed(90, "temperature", "max_tokens")})
    store = FakeLedgerStore()
    await start_run(pinned, store, {ENDPOINT_ID: listings}, "nonce", "test")
    return listings, store


def test_start_run_reads_each_models_listing_for_the_pinned_host_and_stores_it_with_the_run() -> None:
    listings, store = asyncio.run(start_with_listings())

    ((new_run, _),) = store.runs.values()
    assert listings.asked == [("vendor/model", "Pinned")]
    listing = new_run.listings[MODEL]
    assert listing is not None and listing.host == "Pinned"
