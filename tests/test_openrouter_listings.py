"""OpenRouter's model listing over a mocked HTTP layer."""

import asyncio
from datetime import UTC, datetime
from typing import Final

import httpx
from pydantic import JsonValue

from compass_bench.adapters.transport.openrouter_listings import OpenRouterListings

LISTING_BODY: Final[dict[str, JsonValue]] = {
    "data": {
        "id": "vendor/model",
        "created": 1735689600,
        "endpoints": [
            {
                "name": "Host | vendor/model",
                "provider_name": "Host",
                "tag": "host/fp8",
                "quantization": "fp8",
                "supported_parameters": ["temperature", "max_tokens", "top_p"],
            },
            {
                "name": "Host | vendor/model",
                "provider_name": "Host",
                "tag": "host/bf16",
                "quantization": "bf16",
                "supported_parameters": ["temperature"],
            },
        ],
    }
}
# the fields of a listed endpoint as OpenRouter serves them: one provider name covers several tags
PINNED: Final = "host/fp8"


def listings_over(handler: httpx.MockTransport) -> OpenRouterListings:
    return OpenRouterListings("https://openrouter.ai/api/v1/", httpx.AsyncClient(transport=handler))


def test_the_listing_carries_the_listing_date_and_the_pinned_hosts_parameters() -> None:
    requested: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=LISTING_BODY)

    listing = asyncio.run(listings_over(httpx.MockTransport(answer)).listing("vendor/model", PINNED))

    assert requested == ["https://openrouter.ai/api/v1/models/vendor/model/endpoints"]
    assert listing is not None
    assert listing.listed_at == datetime(2025, 1, 1, tzinfo=UTC)
    assert (listing.host, listing.supported_parameters) == (PINNED, ("temperature", "max_tokens", "top_p"))


def test_an_unpinned_endpoint_or_an_unlisted_host_leaves_the_parameters_unknown() -> None:
    reader = listings_over(httpx.MockTransport(lambda request: httpx.Response(200, json=LISTING_BODY)))

    unpinned = asyncio.run(reader.listing("vendor/model", None))
    unlisted = asyncio.run(reader.listing("vendor/model", "Host"))

    assert unpinned is not None and (unpinned.host, unpinned.supported_parameters) == (None, None)
    assert unlisted is not None and (unlisted.host, unlisted.supported_parameters) == ("Host", None)


def test_a_failed_request_or_a_body_without_data_gives_no_listing() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    missing = listings_over(httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "no model"})))
    empty = listings_over(httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []})))

    assert asyncio.run(listings_over(httpx.MockTransport(refuse)).listing("vendor/model", "Pinned")) is None
    assert asyncio.run(missing.listing("vendor/model", "Pinned")) is None
    assert asyncio.run(empty.listing("vendor/model", "Pinned")) is None


def test_a_listing_date_outside_the_datetime_range_is_left_unset() -> None:
    body: dict[str, JsonValue] = {"data": {"id": "vendor/model", "created": 1735689600000, "endpoints": []}}
    reader = listings_over(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))

    listing = asyncio.run(reader.listing("vendor/model", None))

    assert listing is not None and listing.listed_at is None
