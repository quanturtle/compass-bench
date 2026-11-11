"""Record whether each experiment named a preregistration.

A spec stored before experiments could name one gets `preregistration: null`, so every run from before this
revision reads as exploratory. The spec then moves to its new hash, and its runs follow it. The downgrade removes a
null and fails on a named preregistration, which revision 0010 cannot store.

Revision ID: 0011
Revises: 0010
"""

import hashlib
import json
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0011"
down_revision: Final = "0010"
branch_labels = None
depends_on = None

FIELD: Final = "preregistration"


class NamedPreregistration(Exception):
    """An experiment names a preregistration, which revision 0010 cannot store."""


def spec_hash(spec: object) -> str:
    """The experiment hash as the package computes it: SHA-256 of the spec's sorted, compact JSON."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def with_preregistration_field(spec: dict[str, object]) -> dict[str, object]:
    """The spec with a null preregistration; a spec that has the field is returned as it is."""
    if FIELD in spec:
        return spec
    return {**spec, FIELD: None}


def without_preregistration_field(spec: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The spec without the field; raises NamedPreregistration when it names one."""
    if spec.get(FIELD) is not None:
        raise NamedPreregistration(
            f"experiment {stored_hash} names a preregistration, which revision 0010 cannot store"
        )
    return {key: value for key, value in spec.items() if key != FIELD}


def move_experiment(connection: sa.Connection, stored_hash: str, spec: dict[str, object]) -> None:
    """Store `spec` under its own hash, point the runs of `stored_hash` at it, and drop the old row."""
    new_hash = spec_hash(spec)
    if new_hash == stored_hash:
        return
    connection.execute(
        sa.text("INSERT INTO experiments (hash, spec) VALUES (:hash, CAST(:spec AS jsonb)) ON CONFLICT DO NOTHING"),
        {"hash": new_hash, "spec": json.dumps(spec, ensure_ascii=False)},
    )
    connection.execute(
        sa.text("UPDATE runs SET experiment_hash = :new WHERE experiment_hash = :old"),
        {"new": new_hash, "old": stored_hash},
    )
    connection.execute(sa.text("DELETE FROM experiments WHERE hash = :old"), {"old": stored_hash})
    return


def stored_specs(connection: sa.Connection) -> list[tuple[str, dict[str, object]]]:
    return [(row.hash, row.spec) for row in connection.execute(sa.text("SELECT hash, spec FROM experiments"))]


def upgrade() -> None:
    connection = op.get_bind()
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, with_preregistration_field(spec))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, without_preregistration_field(spec, stored_hash))
    return
