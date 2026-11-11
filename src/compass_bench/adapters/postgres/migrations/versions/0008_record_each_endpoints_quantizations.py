"""Record each stored endpoint's quantization filter.

Endpoints stored before the filter existed sent none, so they get an empty list, which allows any precision.
The downgrade removes an empty list and fails on any other, which revision 0007 cannot store.

Revision ID: 0008
Revises: 0007
"""

import json
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0008"
down_revision: Final = "0007"
branch_labels = None
depends_on = None


class FilteredEndpoint(Exception):
    """A run's endpoint filters hosts by precision, which revision 0007 cannot store."""


def with_quantizations(endpoints: dict[str, object]) -> dict[str, object]:
    """Each endpoint with an empty quantization filter; an endpoint that has one is returned as it is."""
    result: dict[str, object] = {}
    for name, settings in endpoints.items():
        assert isinstance(settings, dict)
        result[name] = settings if "quantizations" in settings else {**settings, "quantizations": []}
    return result


def without_quantizations(endpoints: dict[str, object], run_id: str) -> dict[str, object]:
    """Each endpoint without its filter; raises FilteredEndpoint when a filter is not empty."""
    result: dict[str, object] = {}
    for name, settings in endpoints.items():
        assert isinstance(settings, dict)
        if settings.get("quantizations", []):
            raise FilteredEndpoint(
                f"run {run_id} filters endpoint {name!r} by precision, which revision 0007 cannot store"
            )
        result[name] = {key: value for key, value in settings.items() if key != "quantizations"}
    return result


def stored_endpoints(connection: sa.Connection) -> list[tuple[str, dict[str, object]]]:
    return [(row.run_id, row.endpoints) for row in connection.execute(sa.text("SELECT run_id, endpoints FROM runs"))]


def store_endpoints(connection: sa.Connection, run_id: str, endpoints: dict[str, object]) -> None:
    connection.execute(
        sa.text("UPDATE runs SET endpoints = CAST(:endpoints AS jsonb) WHERE run_id = :run_id"),
        {"endpoints": json.dumps(endpoints, ensure_ascii=False), "run_id": run_id},
    )
    return


def upgrade() -> None:
    connection = op.get_bind()
    for run_id, endpoints in stored_endpoints(connection):
        store_endpoints(connection, run_id, with_quantizations(endpoints))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for run_id, endpoints in stored_endpoints(connection):
        store_endpoints(connection, run_id, without_quantizations(endpoints, run_id))
    return
