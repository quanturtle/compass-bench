"""Store each raw response body as the bytes received.

jsonb refuses a NUL or a lone surrogate, so a reply holding one could not be stored. A stored body keeps its jsonb
text as UTF-8 bytes. The downgrade fails on a body that is not JSON.

Revision ID: 0002
Revises: 0001
"""

from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final = "0002"
down_revision: Final = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "attempt_results",
        "raw_body",
        type_=sa.LargeBinary(),
        postgresql_using="convert_to(raw_body::text, 'UTF8')",
    )
    return


def downgrade() -> None:
    op.alter_column(
        "attempt_results",
        "raw_body",
        type_=JSONB(),
        postgresql_using="convert_from(raw_body, 'UTF8')::jsonb",
    )
    return
