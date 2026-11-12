"""rota_ponto: sentido do ponto (AMBOS, IDA ou VOLTA)

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-11-12 09:00:00.000000+00:00

Os pontos que já existem ficam AMBOS, então nada muda para as rotas atuais.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        'rota_ponto',
        sa.Column('sentido', sa.String(length=10), nullable=False, server_default='AMBOS'),
    )
    op.create_check_constraint(
        'ck_rota_ponto_sentido', 'rota_ponto', "sentido IN ('AMBOS', 'IDA', 'VOLTA')"
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint('ck_rota_ponto_sentido', 'rota_ponto', type_='check')
    op.drop_column('rota_ponto', 'sentido')
