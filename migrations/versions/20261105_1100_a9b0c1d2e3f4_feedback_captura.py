"""feedback guarda o tamanho da janela e a imagem da tela no momento do relato

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-05 11:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('feedback', sa.Column('tamanho_tela', sa.String(length=20), nullable=True))
    op.add_column('feedback', sa.Column('captura', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('feedback', 'captura')
    op.drop_column('feedback', 'tamanho_tela')
