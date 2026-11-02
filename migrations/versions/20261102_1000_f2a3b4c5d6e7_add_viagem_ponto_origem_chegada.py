"""add viagem_ponto.origem_chegada

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-02 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("viagem_ponto", sa.Column("origem_chegada", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("viagem_ponto", "origem_chegada")
