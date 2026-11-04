"""feedback guarda o aparelho e a versão do sistema

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-11-04 18:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('feedback', sa.Column('dispositivo', sa.String(length=100), nullable=True))
    op.add_column('feedback', sa.Column('versao_so', sa.String(length=40), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('feedback', 'versao_so')
    op.drop_column('feedback', 'dispositivo')
