"""add rota_aluno.ponto_desembarque_padrao_id e endereco de moradia do aluno

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-30 10:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("rota_aluno", sa.Column("ponto_desembarque_padrao_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_rota_aluno_ponto_desembarque_padrao_id_ponto",
        "rota_aluno",
        "ponto",
        ["ponto_desembarque_padrao_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("endereco", sa.Column("estado", sa.String(length=2), nullable=True))
    op.add_column("endereco", sa.Column("complemento", sa.String(length=100), nullable=True))
    op.add_column("endereco", sa.Column("aluno_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_endereco_aluno_id_aluno",
        "endereco",
        "aluno",
        ["aluno_id"],
        ["usuario_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint("fk_endereco_aluno_id_aluno", "endereco", type_="foreignkey")
    op.drop_column("endereco", "aluno_id")
    op.drop_column("endereco", "complemento")
    op.drop_column("endereco", "estado")
    op.drop_constraint(
        "fk_rota_aluno_ponto_desembarque_padrao_id_ponto", "rota_aluno", type_="foreignkey"
    )
    op.drop_column("rota_aluno", "ponto_desembarque_padrao_id")
