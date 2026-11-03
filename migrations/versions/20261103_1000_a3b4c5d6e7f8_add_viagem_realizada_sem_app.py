"""add viagem.realizada_sem_app

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-03 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "viagem",
        sa.Column("realizada_sem_app", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("viagem", "realizada_sem_app")
