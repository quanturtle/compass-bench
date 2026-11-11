"""Model listings: what a provider says about a slug before any request is sent."""

from typing import Protocol

from compass_bench.domain.listing import ModelListing


class ModelListings(Protocol):
    async def listing(self, slug: str, host: str | None) -> ModelListing | None:
        """The slug's listing with `host`'s supported parameters, or None when the provider returns none.

        Never raises for a transport failure: a listing is provenance, and a run proceeds without it."""
        ...
