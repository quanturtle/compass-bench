"""HTTP failures mapped to TransportError."""

import math
from collections.abc import Mapping
from typing import Final

import httpx
from pydantic import JsonValue

from compass_bench.domain.ledger import TransportError

STATUS_ERRORS: Final[Mapping[int, TransportError]] = {
    400: TransportError.REQUEST_REJECTED,
    401: TransportError.UNAUTHORIZED,
    402: TransportError.PAYMENT_REQUIRED,
    404: TransportError.MODEL_NOT_FOUND,
    408: TransportError.TIMEOUT,
    409: TransportError.SERVER_ERROR,
    422: TransportError.REQUEST_REJECTED,
    429: TransportError.RATE_LIMITED,
}
# OpenRouter's moderation refusal of one input names what it flagged in the error metadata
MODERATION_METADATA_KEYS: Final = frozenset({"reasons", "flagged_input"})


def is_moderation(body: JsonValue) -> bool:
    error = body.get("error") if isinstance(body, dict) else None
    metadata = error.get("metadata") if isinstance(error, dict) else None
    return isinstance(metadata, dict) and not MODERATION_METADATA_KEYS.isdisjoint(metadata)


def classify_status(status: int, body: JsonValue) -> TransportError:
    """A per-request 400, 422, or moderation 403 rejects one request; 401, 402, and 404 are endpoint-level.

    Any other 403 is UNAUTHORIZED, so it opens the circuit too."""
    if status == 403:
        return TransportError.MODERATION if is_moderation(body) else TransportError.UNAUTHORIZED
    if status in STATUS_ERRORS:
        return STATUS_ERRORS[status]
    if status >= 500:
        return TransportError.SERVER_ERROR
    if status >= 400:
        return TransportError.REQUEST_REJECTED
    return TransportError.MALFORMED_BODY


def classify_exception(error: httpx.HTTPError) -> TransportError:
    """A timeout, a connection failure, or a response httpx could not read."""
    if isinstance(error, httpx.TimeoutException):
        return TransportError.TIMEOUT
    if isinstance(error, httpx.TransportError):
        return TransportError.CONNECTION
    return TransportError.MALFORMED_BODY


def retry_after_seconds(headers: httpx.Headers) -> float | None:
    """A Retry-After given in finite seconds; an HTTP date would need the clock, so it counts as absent."""
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return max(0.0, seconds) if math.isfinite(seconds) else None
