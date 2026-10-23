"""add rota_instituicao_ordem

Revision ID: a7b8c9d0e1f2
Revises: f1e2d3c4b5a6
Create Date: 2026-10-23 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f1e2d3c4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table('rota_instituicao_ordem',
    sa.Column('rota_id', sa.UUID(), nullable=False),
    sa.Column('instituicao_id', sa.UUID(), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['rota_id'], ['rota.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['instituicao_id'], ['instituicao.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('rota_id', 'instituicao_id')
    )
    op.create_index('idx_rota_instituicao_ordem_rota_ordem', 'rota_instituicao_ordem', ['rota_id', 'ordem'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('idx_rota_instituicao_ordem_rota_ordem', table_name='rota_instituicao_ordem')
    op.drop_table('rota_instituicao_ordem')
