"""viagem.aviso_parada_enviado evita avisar o motorista parado mais de uma vez

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-11-11 15:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        'viagem',
        sa.Column('aviso_parada_enviado', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('viagem', 'aviso_parada_enviado')
