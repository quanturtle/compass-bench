"""Record each stored reply's response id, provider timestamp, system fingerprint, and native finish reason.

Normalizer version 3 reads them from the response body; a result stored under an earlier version gets them from
its raw body, or null where the body is missing or does not carry them. The downgrade removes them again.

Revision ID: 0009
Revises: 0008
"""

import json
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0009"
down_revision: Final = "0008"
branch_labels = None
depends_on = None

PROVENANCE_VERSION: Final = 3
PROVENANCE_FIELDS: Final = ("response_id", "created_at", "system_fingerprint", "native_finish_reason")


def parsed_body(raw_body: bytes | None) -> dict[str, object]:
    """The raw body as a JSON object, or an empty one when it is missing or not a JSON object."""
    if raw_body is None:
        return {}
    try:
        body = json.loads(raw_body)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def timestamp_or_none(value: object) -> str | None:
    """A Unix timestamp as an ISO 8601 UTC string, as pydantic serializes a datetime; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, UTC).isoformat()


def with_provenance(result: dict[str, object], raw_body: bytes | None) -> dict[str, object]:
    """The result with the four provenance fields on its reply, read from the raw body; a failure is unchanged."""
    if result.get("kind") != "completed":
        return result
    body = parsed_body(raw_body)
    choices = body.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    reply = result["reply"]
    assert isinstance(reply, dict)
    provenance = {
        "response_id": text_or_none(body.get("id")),
        "created_at": timestamp_or_none(body.get("created")),
        "system_fingerprint": text_or_none(body.get("system_fingerprint")),
        "native_finish_reason": text_or_none(choice.get("native_finish_reason")),
    }
    return {**result, "reply": {**reply, **provenance}}


def without_provenance(result: dict[str, object]) -> dict[str, object]:
    if result.get("kind") != "completed":
        return result
    reply = result["reply"]
    assert isinstance(reply, dict)
    return {**result, "reply": {key: value for key, value in reply.items() if key not in PROVENANCE_FIELDS}}


def stored_results(connection: sa.Connection, below_version: int) -> list[tuple[str, dict[str, object], bytes | None]]:
    rows = connection.execute(
        sa.text("SELECT attempt_id, result, raw_body FROM attempt_results WHERE normalizer_version < :version"),
        {"version": below_version},
    )
    return [(row.attempt_id, row.result, bytes(row.raw_body) if row.raw_body is not None else None) for row in rows]


def store_result(connection: sa.Connection, attempt_id: str, result: dict[str, object], version: int) -> None:
    connection.execute(
        sa.text(
            "UPDATE attempt_results SET result = CAST(:result AS jsonb), normalizer_version = :version"
            " WHERE attempt_id = :attempt_id"
        ),
        {"result": json.dumps(result, ensure_ascii=False), "version": version, "attempt_id": attempt_id},
    )
    return


def upgrade() -> None:
    connection = op.get_bind()
    for attempt_id, result, raw_body in stored_results(connection, PROVENANCE_VERSION):
        store_result(connection, attempt_id, with_provenance(result, raw_body), PROVENANCE_VERSION)
    return


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT attempt_id, result FROM attempt_results WHERE normalizer_version = :version"),
        {"version": PROVENANCE_VERSION},
    )
    for row in rows:
        store_result(connection, row.attempt_id, without_provenance(row.result), PROVENANCE_VERSION - 1)
    return
