"""Contagem de queries na listagem de viagens do gestor.

`ViagemListResponseSchema` serializa cada viagem com acessores `fields.Method`
que caminham relações lazy: `obj.horario_rota.rota.alunos_inscritos`,
`obj.alunos_confirmados`, `obj.pontos_visitados`. Sem eager loading, cada
viagem da página dispara o seu próprio conjunto de SELECTs.

Estes testes medem o custo em função do número de viagens. O que caracteriza
N+1 não é o valor absoluto, é a inclinação: se dobrar as viagens dobra as
queries, o problema é estrutural e não some com índice nem com cache.
"""

from datetime import date, timedelta

import pytest

from app.models.enum import StatusViagem
from app.models.rota import RotaAluno
from app.models.viagem import AlunosConfirmados, Viagem
from app.schemas.viagem_schema import ViagemListResponseSchema
from app.services.viagens_service import list_viagens_gestor

pytestmark = pytest.mark.integration


def _monta_viagens(_db, rota, horario_rota, aluno, motorista, quantidade, primeiro_dia=1):
    """Cria `quantidade` viagens na mesma rota, com aluno inscrito e confirmado.

    Cada horário aceita uma viagem por dia, então quem monta duas levas passa `primeiro_dia`.
    """
    if not _db.session.get(RotaAluno, (rota.id, aluno.user.id)):
        _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
        _db.session.flush()

    for i in range(quantidade):
        viagem = Viagem(
            data=date.today() + timedelta(days=primeiro_dia + i),
            horario_rota_id=horario_rota.id,
            status=StatusViagem.AGENDADA,
            motorista_id=motorista.user.id,
        )
        _db.session.add(viagem)
        _db.session.flush()
        _db.session.add(
            AlunosConfirmados(viagem_id=viagem.id, aluno_id=aluno.user.id, confirmacao=True)
        )
    _db.session.commit()


def _queries_para_listar(_db, query_counter, gestor, quantidade):
    _db.session.expire_all()
    with query_counter() as qc:
        viagens = list_viagens_gestor(str(gestor.user.id), {})
        ViagemListResponseSchema().dump({"items": viagens, "total": len(viagens)})
    return len(qc.statements)


def test_listagem_de_viagens_nao_cresce_com_o_numero_de_viagens(
    _db, query_counter, gestor, rota, horario_rota, aluno, motorista
):
    """O teste principal deste arquivo.

    Mede com 2 e com 8 viagens. Num serviço com eager loading o custo é
    praticamente o mesmo nos dois casos: as relações vêm nos mesmos SELECTs.
    Sem eager loading o custo acompanha o número de viagens.

    A margem é generosa de propósito: o objetivo é pegar crescimento linear,
    não fixar um número exato que quebre a cada mudança de schema.
    """
    _monta_viagens(_db, rota, horario_rota, aluno, motorista, 2)
    com_2 = _queries_para_listar(_db, query_counter, gestor, 2)

    _monta_viagens(_db, rota, horario_rota, aluno, motorista, 6, primeiro_dia=3)
    com_8 = _queries_para_listar(_db, query_counter, gestor, 8)

    crescimento = com_8 - com_2
    assert crescimento <= 4, (
        f"{com_2} queries para 2 viagens e {com_8} para 8: "
        f"o custo cresce {crescimento} queries ao somar 6 viagens, "
        "o que é N+1. Falta eager loading nas relações que o schema percorre."
    )


def test_listagem_de_viagens_tem_teto_absoluto(
    _db, query_counter, gestor, rota, horario_rota, aluno, motorista
):
    """Teto de sanidade, separado do teste de inclinação.

    Serve para o caso em que alguém troque lazy por um eager que resolva o
    crescimento mas emita uma quantidade absurda de SELECTs fixos.
    """
    _monta_viagens(_db, rota, horario_rota, aluno, motorista, 8)

    total = _queries_para_listar(_db, query_counter, gestor, 8)

    assert total <= 20, f"{total} queries para listar 8 viagens"
