"""add convite

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-28 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table('convite',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('prefeitura_id', sa.UUID(), nullable=False),
    sa.Column('criado_por_id', sa.UUID(), nullable=True),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('telefone', sa.String(length=20), nullable=True),
    sa.Column('ponto_id', sa.UUID(), nullable=True),
    sa.Column('instituicao_id', sa.UUID(), nullable=True),
    sa.Column('rota_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=True),
    sa.Column('pin_hash', sa.String(length=64), nullable=True),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pin_tentativas', sa.Integer(), nullable=False),
    sa.Column('envio_tentativas', sa.Integer(), nullable=False),
    sa.Column('enviado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('aceito_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('termos_versao', sa.String(length=20), nullable=True),
    sa.Column('aluno_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['prefeitura_id'], ['prefeitura.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['criado_por_id'], ['usuario.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ponto_id'], ['ponto.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['instituicao_id'], ['instituicao.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rota_id'], ['rota.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['aluno_id'], ['aluno.usuario_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('idx_convite_prefeitura_status', 'convite', ['prefeitura_id', 'status'], unique=False)
    op.create_index('uq_convite_aberto_por_email', 'convite', ['prefeitura_id', 'email'], unique=True,
                    postgresql_where=sa.text("status IN ('PENDENTE', 'ENVIADO')"))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index('uq_convite_aberto_por_email', table_name='convite')
    op.drop_index('idx_convite_prefeitura_status', table_name='convite')
    op.drop_table('convite')
