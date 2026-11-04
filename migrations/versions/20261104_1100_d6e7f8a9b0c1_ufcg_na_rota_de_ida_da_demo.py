"""ajuste de dados da demo: o ponto da instituição UFCG entra na rota de ida

A rota "Galante -> UFCG" tinha uma parada comum chamada "UFCG", que não era o ponto da instituição
cadastrada. Alunos da UFCG recebiam "Esta instituição não faz parte da rota da viagem".
A parada da ida passa a ser o ponto da instituição (o mesmo da rota da volta) e a instituição UFCG
duplicada, sem aluno e sem referência, é apagada.

Os ids são os da demo. Em qualquer outro banco nenhuma linha casa e a migração não altera nada.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-04 11:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PONTO_COMUM_UFCG = "692e00dd-8930-4476-9a06-dde1bea5f299"
PONTO_DA_INSTITUICAO = "2558c413-91e4-43d8-8f14-426fa7a4953f"
INSTITUICAO_DUPLICADA = "438d88c3-e1a2-4383-9d37-36df05cc1cad"


def upgrade() -> None:
    """Upgrade database schema."""
    conexao = op.get_bind()

    # Só mexe se o ponto da instituição existe: sem ele a troca deixaria a rota sem a parada.
    existe = conexao.execute(
        sa.text("SELECT 1 FROM ponto WHERE id = :id"), {"id": PONTO_DA_INSTITUICAO}
    ).first()
    if existe is None:
        return

    conexao.execute(
        sa.text(
            "UPDATE rota_ponto SET ponto_id = :novo "
            "WHERE ponto_id = :antigo "
            "AND rota_id = (SELECT id FROM rota WHERE nome = 'Galante -> UFCG')"
        ),
        {"novo": PONTO_DA_INSTITUICAO, "antigo": PONTO_COMUM_UFCG},
    )
    # As viagens agendadas já tinham a parada antiga copiada. As finalizadas ficam como foram.
    conexao.execute(
        sa.text(
            "UPDATE viagem_ponto SET ponto_id = :novo "
            "WHERE ponto_id = :antigo "
            "AND viagem_id IN (SELECT id FROM viagem WHERE status = 'AGENDADA') "
            "AND viagem_id NOT IN (SELECT viagem_id FROM viagem_ponto WHERE ponto_id = :novo)"
        ),
        {"novo": PONTO_DA_INSTITUICAO, "antigo": PONTO_COMUM_UFCG},
    )
    # O ponto aparece como destino da ida e como saída da volta: o nome fica "UFCG".
    conexao.execute(
        sa.text("UPDATE ponto SET apelido = 'UFCG' WHERE id = :id AND apelido = 'UFCG (saída)'"),
        {"id": PONTO_DA_INSTITUICAO},
    )
    conexao.execute(
        sa.text(
            "DELETE FROM instituicao WHERE id = :id "
            "AND NOT EXISTS (SELECT 1 FROM aluno WHERE instituicao_id = :id) "
            "AND NOT EXISTS (SELECT 1 FROM convite WHERE instituicao_id = :id) "
            "AND NOT EXISTS (SELECT 1 FROM rota_instituicao_ordem WHERE instituicao_id = :id)"
        ),
        {"id": INSTITUICAO_DUPLICADA},
    )


def downgrade() -> None:
    """Ajuste de dados sem volta: o backup anterior ao deploy é o caminho para desfazer."""
