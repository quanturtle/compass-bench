"""Store each experiment's equivalence margin in its analysis settings.

A spec stored before experiments could set a margin gets the standard one, 0.1 in score units. The spec then
moves to its new hash, and its runs follow it. The downgrade removes a standard margin and fails on any other,
which revision 0005 cannot store.

Revision ID: 0006
Revises: 0005
"""

import hashlib
import json
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0006"
down_revision: Final = "0005"
branch_labels = None
depends_on = None

# copied, not imported, so later changes to the package leave this revision as it is
STANDARD_MARGIN: Final = 0.1


class CustomMargin(Exception):
    """An experiment sets a margin other than the standard one, which revision 0005 cannot store."""


def spec_hash(spec: object) -> str:
    """The experiment hash as the package computes it: SHA-256 of the spec's sorted, compact JSON."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def with_standard_margin(spec: dict[str, object]) -> dict[str, object]:
    """The spec with the standard margin in its analysis settings; a spec that has one is returned as it is."""
    analysis = spec["analysis"]
    assert isinstance(analysis, dict)
    if "equivalence_margin" in analysis:
        return spec
    return {**spec, "analysis": {**analysis, "equivalence_margin": STANDARD_MARGIN}}


def without_standard_margin(spec: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The spec without its margin; raises CustomMargin when the margin is not the standard one."""
    analysis = spec["analysis"]
    assert isinstance(analysis, dict)
    if analysis.get("equivalence_margin", STANDARD_MARGIN) != STANDARD_MARGIN:
        raise CustomMargin(
            f"experiment {stored_hash} sets its own equivalence margin, which revision 0005 cannot store"
        )
    return {**spec, "analysis": {key: value for key, value in analysis.items() if key != "equivalence_margin"}}


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
        move_experiment(connection, stored_hash, with_standard_margin(spec))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, without_standard_margin(spec, stored_hash))
    return
