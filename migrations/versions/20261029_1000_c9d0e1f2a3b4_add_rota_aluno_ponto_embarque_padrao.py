"""add rota_aluno.ponto_embarque_padrao_id

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-29 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("rota_aluno", sa.Column("ponto_embarque_padrao_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_rota_aluno_ponto_embarque_padrao_id_ponto",
        "rota_aluno",
        "ponto",
        ["ponto_embarque_padrao_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint(
        "fk_rota_aluno_ponto_embarque_padrao_id_ponto", "rota_aluno", type_="foreignkey"
    )
    op.drop_column("rota_aluno", "ponto_embarque_padrao_id")
