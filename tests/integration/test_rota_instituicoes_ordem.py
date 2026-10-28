"""GET/PUT /v1/rotas/{id}/instituicoes/ordem."""

import uuid

import pytest

from app.models.enum import TipoInstituicao
from app.models.geo import Instituicao

pytestmark = pytest.mark.integration


def _cria_inst(_db, prefeitura, nome):
    inst = Instituicao(
        nome=nome,
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        fonte="MANUAL",
        codigo_externo=nome,
        uf="PB",
        prefeitura_id=prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


def _url(rota):
    return f"/v1/rotas/{rota.id}/instituicoes/ordem"


def test_get_vazio(gestor, rota):
    resp = gestor.client.get(_url(rota))

    assert resp.status_code == 200
    assert resp.get_json() == {"items": [], "total": 0}


def test_put_grava_e_get_devolve_na_ordem(_db, motorista, prefeitura, rota):
    a = _cria_inst(_db, prefeitura, "A")
    b = _cria_inst(_db, prefeitura, "B")
    c = _cria_inst(_db, prefeitura, "C")
    ids = [str(c.id), str(a.id), str(b.id)]

    resp = motorista.client.put(_url(rota), json={"instituicao_ids": ids})

    assert resp.status_code == 200
    esperado = {
        "items": [
            {
                "instituicao_id": inst_id,
                "nome": nome,
                "tipo": "Escola Pública",
                "ordem": posicao,
            }
            for posicao, (inst_id, nome) in enumerate(zip(ids, ["C", "A", "B"], strict=True))
        ],
        "total": 3,
    }
    assert resp.get_json() == esperado
    assert motorista.client.get(_url(rota)).get_json() == esperado


def test_put_regrava_e_lista_vazia_limpa(_db, gestor, prefeitura, rota):
    a = _cria_inst(_db, prefeitura, "A")
    b = _cria_inst(_db, prefeitura, "B")
    gestor.client.put(_url(rota), json={"instituicao_ids": [str(a.id), str(b.id)]})

    resp = gestor.client.put(_url(rota), json={"instituicao_ids": [str(b.id)]})
    assert [i["nome"] for i in resp.get_json()["items"]] == ["B"]
    assert resp.get_json()["items"][0]["ordem"] == 0

    resp = gestor.client.put(_url(rota), json={"instituicao_ids": []})
    assert resp.get_json() == {"items": [], "total": 0}


def test_id_repetido_da_400(_db, gestor, prefeitura, rota):
    a = _cria_inst(_db, prefeitura, "A")

    resp = gestor.client.put(_url(rota), json={"instituicao_ids": [str(a.id), str(a.id)]})

    assert resp.status_code == 400


def test_id_inexistente_da_400(gestor, rota):
    resp = gestor.client.put(_url(rota), json={"instituicao_ids": [str(uuid.uuid4())]})

    assert resp.status_code == 400


def test_instituicao_de_outra_prefeitura_da_400(_db, gestor, other_prefeitura, rota):
    outra = _cria_inst(_db, other_prefeitura, "X")

    resp = gestor.client.put(_url(rota), json={"instituicao_ids": [str(outra.id)]})

    assert resp.status_code == 400


def test_aluno_recebe_403(aluno, rota):
    assert aluno.client.get(_url(rota)).status_code == 403
    assert aluno.client.put(_url(rota), json={"instituicao_ids": []}).status_code == 403


def test_gestor_de_outra_prefeitura_recebe_403(other_gestor, rota):
    assert other_gestor.client.get(_url(rota)).status_code == 403


def test_rota_inexistente_da_404(gestor):
    resp = gestor.client.get(f"/v1/rotas/{uuid.uuid4()}/instituicoes/ordem")

    assert resp.status_code == 404


def test_get_sem_n_mais_1(_db, gestor, prefeitura, rota, query_counter):
    ids = []
    for nome in ("A", "B", "C", "D"):
        ids.append(str(_cria_inst(_db, prefeitura, nome).id))
    gestor.client.put(_url(rota), json={"instituicao_ids": ids})

    with query_counter() as qc:
        resp = gestor.client.get(_url(rota))

    assert resp.status_code == 200
    assert len(qc.matching("from instituicao")) <= 1, qc.report()
