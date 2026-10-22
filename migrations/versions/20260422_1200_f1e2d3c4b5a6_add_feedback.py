"""add feedback

Revision ID: f1e2d3c4b5a6
Revises: d4e5f6a7b8c9
Create Date: 2026-10-22 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table('feedback',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('usuario_id', sa.UUID(), nullable=True),
    sa.Column('prefeitura_id', sa.UUID(), nullable=True),
    sa.Column('tipo', sa.Enum('BUG', 'SUGESTAO', 'DUVIDA', name='tipo_feedback'), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('tela', sa.String(length=100), nullable=True),
    sa.Column('versao_app', sa.String(length=30), nullable=True),
    sa.Column('plataforma', sa.String(length=20), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['prefeitura_id'], ['prefeitura.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_feedback_created_at', 'feedback', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('idx_feedback_created_at', table_name='feedback')
    op.drop_table('feedback')
    sa.Enum(name='tipo_feedback').drop(op.get_bind(), checkfirst=True)
