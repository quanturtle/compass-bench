"""Name the answer type: each model's `format` becomes `answer_type`, and the template's {reply_format} becomes
{answer_instruction}.

The rendered prompts do not change, so every stored attempt still carries the prompt its trial renders. Each spec
then moves to its new hash, and its runs follow it. The downgrade restores both names.

Revision ID: 0004
Revises: 0003
"""

import hashlib
import json
from string import Formatter
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0004"
down_revision: Final = "0003"
branch_labels = None
depends_on = None

# the names before and after, as (revision 0003's, this revision's)
MODEL_KEYS: Final = ("format", "answer_type")
TEMPLATE_FIELDS: Final = ("reply_format", "answer_instruction")


def spec_hash(spec: object) -> str:
    """The experiment hash as the package computes it: SHA-256 of the spec's sorted, compact JSON."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def renamed_field(template: str, old: str, new: str) -> str:
    """The template with its field `old` named `new`; literal braces stay doubled."""
    parts: list[str] = []
    for literal, field, _, _ in Formatter().parse(template):
        parts.append(literal.replace("{", "{{").replace("}", "}}"))
        if field is not None:
            parts.append("{" + (new if field == old else field) + "}")
    return "".join(parts)


def renamed_spec(spec: dict[str, object], keys: tuple[str, str], fields: tuple[str, str]) -> dict[str, object]:
    """The spec with each model's key keys[0] named keys[1], and the template's field fields[0] named fields[1]."""
    models, design = spec["models"], spec["design"]
    assert isinstance(models, dict) and isinstance(design, dict)
    prompt = design["prompt"]
    assert isinstance(prompt, dict) and isinstance(prompt["template"], str)
    renamed_models = {
        name: {(keys[1] if key == keys[0] else key): value for key, value in model.items()}
        for name, model in models.items()
    }
    template = renamed_field(prompt["template"], *fields)
    return {**spec, "models": renamed_models, "design": {**design, "prompt": {**prompt, "template": template}}}


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
        move_experiment(connection, stored_hash, renamed_spec(spec, MODEL_KEYS, TEMPLATE_FIELDS))
    return


def downgrade() -> None:
    connection = op.get_bind()
    reversed_keys, reversed_fields = (MODEL_KEYS[1], MODEL_KEYS[0]), (TEMPLATE_FIELDS[1], TEMPLATE_FIELDS[0])
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, renamed_spec(spec, reversed_keys, reversed_fields))
    return
