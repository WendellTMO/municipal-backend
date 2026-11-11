"""viagem: uma viagem por horario em cada dia

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-11-11 18:00:00.000000+00:00

Se o banco já tiver duas viagens no mesmo horário e dia, a migration falha e nada é
alterado. Nesse caso é preciso decidir à mão qual das duas manter.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_unique_constraint(
        'uq_viagem_horario_data', 'viagem', ['horario_rota_id', 'data']
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint('uq_viagem_horario_data', 'viagem', type_='unique')
