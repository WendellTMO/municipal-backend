"""evento_telemetria guarda os eventos de uso enviados pelo app

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-11-09 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        'evento_telemetria',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('usuario_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('papel', sa.String(length=12), nullable=True),
        sa.Column('sessao_id', sa.String(length=40), nullable=False),
        sa.Column('tipo', sa.String(length=12), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('props', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('versao_app', sa.String(length=30), nullable=True),
        sa.Column('plataforma', sa.String(length=20), nullable=True),
        sa.Column('dispositivo', sa.String(length=100), nullable=True),
        sa.Column('versao_so', sa.String(length=40), nullable=True),
        sa.Column('ocorrido_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recebido_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_evento_telemetria_recebido', 'evento_telemetria', ['recebido_em'])
    op.create_index('idx_evento_telemetria_tipo_nome', 'evento_telemetria', ['tipo', 'nome'])


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('idx_evento_telemetria_tipo_nome', table_name='evento_telemetria')
    op.drop_index('idx_evento_telemetria_recebido', table_name='evento_telemetria')
    op.drop_table('evento_telemetria')
