"""aluno_instituicao guarda as instituições extras de cada aluno

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-09 15:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        'aluno_instituicao',
        sa.Column('aluno_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('instituicao_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['aluno_id'], ['usuario.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['instituicao_id'], ['instituicao.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('aluno_id', 'instituicao_id'),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table('aluno_instituicao')
