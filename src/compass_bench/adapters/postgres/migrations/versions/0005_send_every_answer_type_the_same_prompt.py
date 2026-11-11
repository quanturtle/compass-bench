"""Send every answer type the same prompt: a template no longer has an {answer_instruction} field.

Revision 0004 filled that field with the sentence of the experiment's answer type. Each stored spec gets that sentence
written into its template as text, so its runs render the prompts they were sent. The spec then moves to its new hash,
and its runs follow it. The downgrade puts the field back where the sentence stands, and refuses a spec whose template
lacks its answer type's sentence, which revision 0004 cannot render.

Revision ID: 0005
Revises: 0004
"""

import hashlib
import json
from collections.abc import Mapping
from string import Formatter
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0005"
down_revision: Final = "0004"
branch_labels = None
depends_on = None

FIELD: Final = "answer_instruction"
# copied, not imported, so later changes to the package leave this revision as it is
SENTENCES: Final[Mapping[str, str]] = {
    "free_text": "Reply with a single number from the scale below and nothing else.",
    "structured": 'Reply with a JSON object whose "rating" member is a single number from the scale below.',
}


class UnrenderableSpec(Exception):
    """A spec that the target revision cannot render as its runs were sent."""


def spec_hash(spec: object) -> str:
    """The experiment hash as the package computes it: SHA-256 of the spec's sorted, compact JSON."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def escaped(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def answer_sentence(spec: dict[str, object], stored_hash: str) -> str:
    """The sentence of the spec's one answer type; raises UnrenderableSpec when its models use several."""
    models = spec["models"]
    assert isinstance(models, dict)
    answer_types = {model["answer_type"] for model in models.values()}
    if len(answer_types) != 1:
        raise UnrenderableSpec(f"experiment {stored_hash} uses answer types {sorted(answer_types)}, not one")
    return SENTENCES[answer_types.pop()]


def with_template(spec: dict[str, object], template: str) -> dict[str, object]:
    design = spec["design"]
    assert isinstance(design, dict) and isinstance(design["prompt"], dict)
    return {**spec, "design": {**design, "prompt": {**design["prompt"], "template": template}}}


def stored_template(spec: dict[str, object]) -> str:
    design = spec["design"]
    assert isinstance(design, dict) and isinstance(design["prompt"], dict)
    template = design["prompt"]["template"]
    assert isinstance(template, str)
    return template


def with_sentence(spec: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The spec with its {answer_instruction} field replaced by its answer type's sentence, as template text."""
    template = stored_template(spec)
    if FIELD not in {field for _, field, _, _ in Formatter().parse(template)}:
        return spec
    sentence = escaped(answer_sentence(spec, stored_hash))
    parts: list[str] = []
    for literal, field, _, _ in Formatter().parse(template):
        parts.append(escaped(literal))
        if field is not None:
            parts.append(sentence if field == FIELD else "{" + field + "}")
    return with_template(spec, "".join(parts))


def with_field(spec: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The spec with its answer type's sentence replaced by the {answer_instruction} field."""
    template = stored_template(spec)
    sentence = escaped(answer_sentence(spec, stored_hash))
    if template.count(sentence) != 1:
        raise UnrenderableSpec(f"experiment {stored_hash} does not ask its answer type's sentence once")
    return with_template(spec, template.replace(sentence, "{" + FIELD + "}"))


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
        move_experiment(connection, stored_hash, with_sentence(spec, stored_hash))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for stored_hash, spec in stored_specs(connection):
        move_experiment(connection, stored_hash, with_field(spec, stored_hash))
    return
