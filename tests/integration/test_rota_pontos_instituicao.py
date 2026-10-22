"""GET /v1/rotas/{id}/pontos devolve a instituição de ensino de cada ponto."""

import pytest

from app.models.enum import TipoInstituicao
from app.models.geo import Instituicao
from app.models.rota import RotaPonto
from tests.factories.geo_factory import PontoFactory

pytestmark = pytest.mark.integration


def _cria_instituicao(_db, prefeitura, ponto, nome="UFCG"):
    inst = Instituicao(
        nome=nome,
        tipo=TipoInstituicao.UNIVERSIDADE_PUBLICA,
        fonte="MANUAL",
        codigo_externo=nome,
        uf="PB",
        prefeitura_id=prefeitura.id,
        ponto_id=ponto.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


def test_ponto_sem_instituicao_devolve_null(gestor, rota, rota_ponto):
    resp = gestor.client.get(f"/v1/rotas/{rota.id}/pontos")

    assert resp.status_code == 200
    assert resp.get_json()["items"][0]["instituicao"] is None


def test_ponto_com_instituicao_devolve_id_nome_e_tipo(
    _db, gestor, prefeitura, rota, ponto, rota_ponto
):
    inst = _cria_instituicao(_db, prefeitura, ponto)

    resp = gestor.client.get(f"/v1/rotas/{rota.id}/pontos")

    assert resp.status_code == 200
    assert resp.get_json()["items"][0]["instituicao"] == {
        "id": str(inst.id),
        "nome": "UFCG",
        "tipo": "Universidade Pública",
    }


def test_varios_pontos_nao_fazem_n_mais_1(
    _db, gestor, prefeitura, rota, ponto, rota_ponto, query_counter
):
    _cria_instituicao(_db, prefeitura, ponto)
    for ordem in (2, 3, 4):
        outro = PontoFactory(prefeitura_id=prefeitura.id)
        _db.session.add(outro)
        _db.session.flush()
        _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=outro.id, ordem=ordem))
    _db.session.commit()

    with query_counter() as qc:
        resp = gestor.client.get(f"/v1/rotas/{rota.id}/pontos")

    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) == 4
    assert len(qc.matching("from instituicao")) <= 1, qc.report()
    assert len(qc.matching("from ponto")) <= 1, qc.report()
