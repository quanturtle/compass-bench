"""OpenRouter's model listing: `GET /models/{slug}/endpoints`, which needs no key."""

from typing import Final

import httpx
from pydantic import JsonValue

from compass_bench.adapters.transport.openrouter import timestamp_or_none
from compass_bench.domain.listing import ModelListing

ENDPOINTS_PATH: Final = "/models/{slug}/endpoints"


def host_parameters(data: dict[str, JsonValue], host: str | None) -> tuple[str, ...] | None:
    """The supported parameters of the endpoint whose `tag` is `host`; None without a match.
    The tag is the routing slug a provider order names; `provider_name` is a display name several tags share."""
    endpoints = data.get("endpoints")
    if host is None or not isinstance(endpoints, list):
        return None
    for endpoint in endpoints:
        if isinstance(endpoint, dict) and endpoint.get("tag") == host:
            parameters = endpoint.get("supported_parameters")
            if isinstance(parameters, list):
                return tuple(parameter for parameter in parameters if isinstance(parameter, str))
    return None


def parse_listing(body: JsonValue, host: str | None) -> ModelListing | None:
    """The listing in a 2xx body, or None when the body carries no `data` object."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    listed_at = timestamp_or_none(data.get("created"))
    return ModelListing(listed_at=listed_at, host=host, supported_parameters=host_parameters(data, host))


class OpenRouterListings:
    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self.base_url = base_url
        self.client = client
        return

    async def listing(self, slug: str, host: str | None) -> ModelListing | None:
        url = self.base_url.rstrip("/") + ENDPOINTS_PATH.format(slug=slug)
        try:
            response = await self.client.get(url)
        except httpx.HTTPError:
            return None
        if not response.is_success:
            return None
        try:
            body: JsonValue = response.json()
        except ValueError:
            return None
        return parse_listing(body, host)
