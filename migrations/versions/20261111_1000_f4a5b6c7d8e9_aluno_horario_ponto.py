"""aluno_horario_ponto guarda os pontos que o aluno usa em cada horário da rota

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-11 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        'aluno_horario_ponto',
        sa.Column('aluno_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('horario_rota_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ponto_embarque_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ponto_desembarque_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['aluno_id'], ['aluno.usuario_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['horario_rota_id'], ['horario_rota.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ponto_embarque_id'], ['ponto.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ponto_desembarque_id'], ['ponto.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('aluno_id', 'horario_rota_id'),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table('aluno_horario_ponto')
