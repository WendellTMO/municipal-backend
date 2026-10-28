"""Ponto de embarque padrão do aluno: /v1/rotas/<id>/meu-ponto-embarque e agenda."""

import pytest

from app.models.geo import Ponto
from app.models.rota import RotaPonto

pytestmark = pytest.mark.integration


def _url(rota):
    return f"/v1/rotas/{rota.id}/meu-ponto-embarque"


def test_get_sem_padrao_devolve_nulos(aluno, rota, rota_aluno):
    r = aluno.client.get(_url(rota))
    assert r.status_code == 200
    assert r.get_json() == {"rota_id": str(rota.id), "ponto_id": None, "ponto_apelido": None}


def test_put_e_get_do_padrao(aluno, rota, rota_aluno, rota_ponto, ponto):
    r = aluno.client.put(_url(rota), json={"ponto_id": str(ponto.id)})
    assert r.status_code == 200, r.get_data(as_text=True)
    esperado = {"rota_id": str(rota.id), "ponto_id": str(ponto.id), "ponto_apelido": ponto.apelido}
    assert r.get_json() == esperado
    assert aluno.client.get(_url(rota)).get_json() == esperado


def test_put_ponto_fora_da_rota_da_400(_db, aluno, prefeitura, rota, rota_aluno, rota_ponto):
    fora = Ponto(prefeitura_id=prefeitura.id, latitude=-7.2, longitude=-35.9, apelido="Fora")
    _db.session.add(fora)
    _db.session.commit()
    r = aluno.client.put(_url(rota), json={"ponto_id": str(fora.id)})
    assert r.status_code == 400


def test_put_sem_ponto_id_da_400(aluno, rota, rota_aluno):
    assert aluno.client.put(_url(rota), json={}).status_code == 400


def test_aluno_nao_inscrito_recebe_403(aluno, rota, rota_ponto, ponto):
    assert aluno.client.get(_url(rota)).status_code == 403
    assert aluno.client.put(_url(rota), json={"ponto_id": str(ponto.id)}).status_code == 403


def test_gestor_recebe_403(gestor, rota, ponto):
    assert gestor.client.get(_url(rota)).status_code == 403
    assert gestor.client.put(_url(rota), json={"ponto_id": str(ponto.id)}).status_code == 403


def test_sem_token_nao_acessa(client, rota):
    assert client.get(_url(rota)).status_code in (401, 422)


def test_agenda_traz_o_padrao_quando_nao_ha_confirmacao(
    _db, aluno, rota, rota_aluno, rota_ponto, ponto, viagem_futura_agendada_com_motorista
):
    sem_padrao = aluno.client.get("/v1/viagens/aluno/agenda").get_json()["items"][0]
    assert sem_padrao["ponto_embarque_id"] is None

    aluno.client.put(_url(rota), json={"ponto_id": str(ponto.id)})
    com_padrao = aluno.client.get("/v1/viagens/aluno/agenda").get_json()["items"][0]
    assert com_padrao["ponto_embarque_id"] == str(ponto.id)
    assert com_padrao["status_confirmacao"] is False


def test_agenda_prefere_o_ponto_da_confirmacao(
    _db,
    aluno,
    prefeitura,
    rota,
    rota_aluno,
    rota_ponto,
    ponto,
    viagem_futura_agendada_com_motorista,
):
    outro = Ponto(prefeitura_id=prefeitura.id, latitude=-7.3, longitude=-35.8, apelido="Outro")
    _db.session.add(outro)
    _db.session.flush()
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=outro.id, ordem=2))
    _db.session.commit()
    aluno.client.put(_url(rota), json={"ponto_id": str(ponto.id)})
    viagem_id = viagem_futura_agendada_com_motorista.id
    aluno.client.put(
        f"/v1/viagens/{viagem_id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": str(outro.id)},
    )
    item = aluno.client.get("/v1/viagens/aluno/agenda").get_json()["items"][0]
    assert item["ponto_embarque_id"] == str(outro.id)


def test_confirmar_sem_corpo_de_ponto_usa_o_padrao_via_api(
    aluno, rota, rota_aluno, rota_ponto, ponto, viagem_futura_agendada_com_motorista
):
    url = f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao"
    assert aluno.client.put(url, json={"confirmacao": True}).status_code == 400
    aluno.client.put(_url(rota), json={"ponto_id": str(ponto.id)})
    r = aluno.client.put(url, json={"confirmacao": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ponto_embarque"] == ponto.apelido
