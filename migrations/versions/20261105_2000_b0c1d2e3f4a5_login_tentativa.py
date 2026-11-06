"""login_tentativa guarda as falhas seguidas de login por e-mail

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-11-05 20:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        'login_tentativa',
        sa.Column('chave', sa.String(length=160), nullable=False),
        sa.Column('falhas', sa.Integer(), nullable=False),
        sa.Column('bloqueado_ate', sa.DateTime(timezone=True), nullable=True),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('chave'),
    )
    op.create_index('idx_login_tentativa_atualizado', 'login_tentativa', ['atualizado_em'])


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('idx_login_tentativa_atualizado', table_name='login_tentativa')
    op.drop_table('login_tentativa')
