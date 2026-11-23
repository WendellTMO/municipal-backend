"""demo: localizacao do onibus compartilhada pelos alunos (viagem_relato)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-11-23 10:00:00.000000+00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        'viagem', sa.Column('pedido_colaborativo_em', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        'viagem_relato',
        sa.Column('viagem_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('aluno_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('precisao_m', sa.Float(), nullable=False),
        sa.Column('recebido_em', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['viagem_id'], ['viagem.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['aluno_id'], ['aluno.usuario_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('viagem_id', 'aluno_id'),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table('viagem_relato')
    op.drop_column('viagem', 'pedido_colaborativo_em')
