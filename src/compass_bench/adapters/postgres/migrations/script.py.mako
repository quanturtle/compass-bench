"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from typing import Final

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: Final = ${repr(up_revision)}
down_revision: Final = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}
    return


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
    return
