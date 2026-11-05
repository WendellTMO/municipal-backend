"""usuario guarda quando a senha mudou e a trava de tentativas da troca de senha

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-05 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('usuario', sa.Column('senha_alterada_em', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'usuario',
        sa.Column('falhas_troca_senha', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'usuario', sa.Column('troca_senha_bloqueada_ate', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('usuario', 'troca_senha_bloqueada_ate')
    op.drop_column('usuario', 'falhas_troca_senha')
    op.drop_column('usuario', 'senha_alterada_em')
