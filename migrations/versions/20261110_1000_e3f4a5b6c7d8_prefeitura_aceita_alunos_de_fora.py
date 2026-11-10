"""prefeitura.aceita_alunos_de_fora libera as rotas para alunos de outras prefeituras

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-10 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        'prefeitura',
        sa.Column('aceita_alunos_de_fora', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('prefeitura', 'aceita_alunos_de_fora')
