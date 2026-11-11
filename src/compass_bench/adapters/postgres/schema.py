"""The only schema declaration. Alembic migrations are generated from it and CI checks they match."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

# ledger: rows are written once and never updated

questionnaires = Table(
    "questionnaires",
    metadata,
    Column("hash", Text, primary_key=True),
    Column("document", JSONB, nullable=False),
)

experiments = Table(
    "experiments",
    metadata,
    Column("hash", Text, primary_key=True),
    Column("spec", JSONB, nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("experiment_hash", Text, ForeignKey("experiments.hash"), nullable=False),
    Column("nonce", Text, nullable=False),
    Column("code_revision", Text, nullable=False),
    Column("endpoints", JSONB, nullable=False),
    # each model's provider listing when the run started; runs from before the column have none
    Column("listings", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

run_events = Table(
    "run_events",
    metadata,
    Column("run_id", Text, ForeignKey("runs.run_id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("run_id", "seq"),
)

trials = Table(
    "trials",
    metadata,
    Column("trial_key", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("runs.run_id"), nullable=False),
    Column("model_id", Text, nullable=False),
    Column("question_id", Text, nullable=False),
    Column("polarity", Integer, nullable=False),
    Column("condition_id", Text, nullable=False),
    Column("repetition", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    UniqueConstraint("run_id", "position"),
)

attempts = Table(
    "attempts",
    metadata,
    Column("attempt_id", Text, primary_key=True),
    Column("trial_key", Text, ForeignKey("trials.trial_key"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("prompt", JSONB, nullable=False),
    Column("request", JSONB, nullable=False),
    Column("reserved_usd", Numeric, nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("trial_key", "seq"),
)

attempt_results = Table(
    "attempt_results",
    metadata,
    Column("attempt_id", Text, ForeignKey("attempts.attempt_id"), primary_key=True),
    # the response bytes as received; jsonb would refuse a NUL or a lone surrogate in them
    Column("raw_body", LargeBinary),
    Column("result", JSONB, nullable=False),
    Column("normalizer_version", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
