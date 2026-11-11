"""Create the ledger tables.

Revision ID: 0001
Revises:
"""

from datetime import datetime
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final = "0001"
down_revision: Final = None
branch_labels = None
depends_on = None

TABLES_IN_CREATION_ORDER: Final = (
    "questionnaires",
    "experiments",
    "runs",
    "run_events",
    "trials",
    "attempts",
    "attempt_results",
)


def inserted_at(name: str) -> sa.Column[datetime]:
    """A timestamp the database stamps on insert."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "questionnaires",
        sa.Column("hash", sa.Text(), primary_key=True),
        sa.Column("document", JSONB(), nullable=False),
    )
    op.create_table(
        "experiments",
        sa.Column("hash", sa.Text(), primary_key=True),
        sa.Column("spec", JSONB(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("experiment_hash", sa.Text(), sa.ForeignKey("experiments.hash"), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("code_revision", sa.Text(), nullable=False),
        sa.Column("endpoints", JSONB(), nullable=False),
        inserted_at("created_at"),
    )
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("detail", JSONB(), nullable=False),
        inserted_at("at"),
        sa.PrimaryKeyConstraint("run_id", "seq"),
    )
    op.create_table(
        "trials",
        sa.Column("trial_key", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("polarity", sa.Integer(), nullable=False),
        sa.Column("condition_id", sa.Text(), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "position"),
    )
    op.create_table(
        "attempts",
        sa.Column("attempt_id", sa.Text(), primary_key=True),
        sa.Column("trial_key", sa.Text(), sa.ForeignKey("trials.trial_key"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("prompt", JSONB(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(), nullable=False),
        inserted_at("sent_at"),
        sa.UniqueConstraint("trial_key", "seq"),
    )
    op.create_table(
        "attempt_results",
        sa.Column("attempt_id", sa.Text(), sa.ForeignKey("attempts.attempt_id"), primary_key=True),
        sa.Column("raw_body", JSONB()),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("normalizer_version", sa.Integer(), nullable=False),
        inserted_at("received_at"),
    )
    return


def downgrade() -> None:
    for table in reversed(TABLES_IN_CREATION_ORDER):
        op.drop_table(table)
    return
