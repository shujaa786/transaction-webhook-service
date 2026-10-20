"""add outbox claim lease

Revision ID: c057fa4f6e58
Revises: 9c5195686c58
Create Date: 2026-10-21 01:08:49.610202

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c057fa4f6e58"
down_revision: Union[str, Sequence[str], None] = "9c5195686c58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column(
            "claimed_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "claimed_until")
