"""GET /v1/viagens/minhas devolve a instituição de cada aluno da viagem."""

import pytest

from app.models.enum import TipoInstituicao
from app.models.geo import Instituicao
from app.models.viagem import AlunosConfirmados
from tests.factories.user_factory import AlunoFactory

pytestmark = pytest.mark.integration


def _cria_instituicao(_db, prefeitura, codigo="ufcg"):
    inst = Instituicao(
        nome="UFCG",
        tipo=TipoInstituicao.UNIVERSIDADE_PUBLICA,
        fonte="MANUAL",
        codigo_externo=codigo,
        uf="PB",
        prefeitura_id=prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


def _confirma(_db, viagem, aluno_user, ponto):
    _db.session.add(
        AlunosConfirmados(
            viagem_id=viagem.id,
            aluno_id=aluno_user.id,
            confirmacao=True,
            ponto_embarque_id=ponto.id,
            ponto_destino_id=ponto.id,
        )
    )
    _db.session.commit()


def test_aluno_com_instituicao(
    _db, motorista, prefeitura, aluno, ponto, viagem_futura_agendada_com_motorista
):
    inst = _cria_instituicao(_db, prefeitura)
    aluno.user.instituicao_id = inst.id
    _db.session.commit()
    _confirma(_db, viagem_futura_agendada_com_motorista, aluno.user, ponto)

    resp = motorista.client.get("/v1/viagens/minhas")

    assert resp.status_code == 200
    item = resp.get_json()["items"][0]["alunos"][0]
    assert item["instituicao"] == {
        "id": str(inst.id),
        "nome": "UFCG",
        "tipo": "Universidade Pública",
    }


def test_aluno_sem_instituicao_devolve_null(
    _db, motorista, aluno, ponto, viagem_futura_agendada_com_motorista
):
    _confirma(_db, viagem_futura_agendada_com_motorista, aluno.user, ponto)

    resp = motorista.client.get("/v1/viagens/minhas")

    assert resp.get_json()["items"][0]["alunos"][0]["instituicao"] is None


def test_varios_alunos_nao_fazem_n_mais_1(
    _db, motorista, prefeitura, ponto, viagem_futura_agendada_com_motorista, query_counter
):
    for i in range(4):
        # uma instituição por aluno, senão o identity map esconde o N+1
        inst = _cria_instituicao(_db, prefeitura, codigo=f"inst{i}")
        a = AlunoFactory(prefeitura_id=prefeitura.id, instituicao_id=inst.id)
        _db.session.add(a)
        _db.session.commit()
        _confirma(_db, viagem_futura_agendada_com_motorista, a, ponto)

    with query_counter() as qc:
        resp = motorista.client.get("/v1/viagens/minhas")

    assert len(resp.get_json()["items"][0]["alunos"]) == 4
    assert len(qc.matching("from instituicao")) <= 1, qc.report()
