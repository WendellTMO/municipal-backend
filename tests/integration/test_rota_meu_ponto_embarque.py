"""Pontos lembrados do aluno: /v1/rotas/<id>/meu-ponto-embarque."""

import pytest

from app.models.geo import Ponto
from app.models.rota import RotaAluno

pytestmark = pytest.mark.integration


def _url(rota):
    return f"/v1/rotas/{rota.id}/meu-ponto-embarque"


def _ponto_fora(_db, prefeitura):
    fora = Ponto(prefeitura_id=prefeitura.id, latitude=-7.2, longitude=-35.9, apelido="Fora")
    _db.session.add(fora)
    _db.session.commit()
    return fora


def test_get_sem_padrao_devolve_nulos(aluno, rota, rota_aluno):
    r = aluno.client.get(_url(rota))
    assert r.status_code == 200
    assert r.get_json() == {
        "rota_id": str(rota.id),
        "ponto_embarque": None,
        "ponto_desembarque": None,
    }


def test_put_e_get_dos_padroes(aluno, rota, rota_aluno, rota_ponto, ponto):
    corpo = {"ponto_embarque_id": str(ponto.id), "ponto_desembarque_id": str(ponto.id)}
    r = aluno.client.put(_url(rota), json=corpo)
    assert r.status_code == 200, r.get_data(as_text=True)
    resumo = {"id": str(ponto.id), "apelido": ponto.apelido}
    esperado = {"rota_id": str(rota.id), "ponto_embarque": resumo, "ponto_desembarque": resumo}
    assert r.get_json() == esperado
    assert aluno.client.get(_url(rota)).get_json() == esperado


def test_put_de_um_lado_preserva_o_outro(_db, aluno, rota, rota_aluno, rota_ponto, ponto):
    aluno.client.put(_url(rota), json={"ponto_embarque_id": str(ponto.id)})
    r = aluno.client.put(_url(rota), json={"ponto_desembarque_id": str(ponto.id)})
    assert r.get_json()["ponto_embarque"]["id"] == str(ponto.id)
    assert r.get_json()["ponto_desembarque"]["id"] == str(ponto.id)


@pytest.mark.parametrize("campo", ["ponto_embarque_id", "ponto_desembarque_id"])
def test_put_ponto_fora_da_rota_da_400_com_o_campo(
    _db, aluno, prefeitura, rota, rota_aluno, rota_ponto, campo
):
    fora = _ponto_fora(_db, prefeitura)
    r = aluno.client.put(_url(rota), json={campo: str(fora.id)})
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == campo


def test_put_sem_pontos_da_400(aluno, rota, rota_aluno):
    assert aluno.client.put(_url(rota), json={}).status_code == 400


def test_delete_esquece_os_dois(_db, aluno, rota, rota_aluno, rota_ponto, ponto):
    aluno.client.put(
        _url(rota), json={"ponto_embarque_id": str(ponto.id), "ponto_desembarque_id": str(ponto.id)}
    )
    r = aluno.client.delete(_url(rota))
    assert r.status_code == 200
    assert r.get_json() == {
        "rota_id": str(rota.id),
        "ponto_embarque": None,
        "ponto_desembarque": None,
    }
    inscricao = _db.session.get(RotaAluno, (rota.id, aluno.user.id))
    assert inscricao.ponto_embarque_padrao_id is None
    assert inscricao.ponto_desembarque_padrao_id is None


def test_aluno_nao_inscrito_recebe_403(aluno, rota, rota_ponto, ponto):
    corpo = {"ponto_embarque_id": str(ponto.id)}
    assert aluno.client.get(_url(rota)).status_code == 403
    assert aluno.client.put(_url(rota), json=corpo).status_code == 403
    assert aluno.client.delete(_url(rota)).status_code == 403


def test_gestor_recebe_403(gestor, rota, ponto):
    corpo = {"ponto_embarque_id": str(ponto.id)}
    assert gestor.client.get(_url(rota)).status_code == 403
    assert gestor.client.put(_url(rota), json=corpo).status_code == 403
    assert gestor.client.delete(_url(rota)).status_code == 403


def test_sem_token_nao_acessa(client, rota):
    assert client.get(_url(rota)).status_code in (401, 422)
    assert client.delete(_url(rota)).status_code in (401, 422)
