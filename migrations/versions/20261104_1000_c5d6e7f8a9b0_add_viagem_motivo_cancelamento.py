"""add viagem.motivo_cancelamento

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-04 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("viagem", sa.Column("motivo_cancelamento", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("viagem", "motivo_cancelamento")
