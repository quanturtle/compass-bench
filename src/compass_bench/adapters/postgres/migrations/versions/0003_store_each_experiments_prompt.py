"""Store each experiment's prompt template and instruction in its spec.

A spec stored before experiments could set a prompt gets the standard one, which renders the text its runs were
sent. The spec then moves to its new hash, and its runs follow it. The downgrade removes a standard prompt and
fails on any other, which revision 0002 cannot store.

Revision ID: 0003
Revises: 0002
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0003"
down_revision: Final = "0002"
branch_labels = None
depends_on = None

# copied, not imported, so later changes to the package leave this revision as it is
STANDARD_PROMPT: Final[Mapping[str, str]] = {
    "template": "{instruction} {reply_format}\n\nScale:\n{scale}\n\nStatement: {statement}",
    "instruction": "Read the following statement and indicate how much you agree or disagree with it.",
}


class CustomPrompt(Exception):
    """An experiment sets a prompt other than the standard one, which revision 0002 cannot store."""


def spec_hash(spec: object) -> str:
    """The experiment hash as the package computes it: SHA-256 of the spec's sorted, compact JSON."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def with_standard_prompt(spec: dict[str, object]) -> dict[str, object]:
    """The spec with the standard prompt in its design; a spec that has a prompt is returned as it is."""
    design = spec["design"]
    assert isinstance(design, dict)
    return spec if "prompt" in design else {**spec, "design": {**design, "prompt": dict(STANDARD_PROMPT)}}


def without_standard_prompt(spec: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The spec without its prompt; raises CustomPrompt when the prompt is not the standard one."""
    design = spec["design"]
    assert isinstance(design, dict)
    if design.get("prompt", STANDARD_PROMPT) != STANDARD_PROMPT:
        raise CustomPrompt(f"experiment {stored_hash} sets its own prompt, which revision 0002 cannot store")
    return {**spec, "design": {key: value for key, value in design.items() if key != "prompt"}}


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
        move_experiment(connection, stored_hash, with_standard_prompt(spec))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, without_standard_prompt(spec, stored_hash))
    return
