"""Record what the provider listed for each model's slug when a run started.

Runs from before the column get an empty object: nothing was listed for them.

Revision ID: 0010
Revises: 0009
"""

from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final = "0010"
down_revision: Final = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("listings", JSONB(), nullable=False, server_default="{}"))
    return


def downgrade() -> None:
    op.drop_column("runs", "listings")
    return
