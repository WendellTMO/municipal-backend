"""Nenhuma resposta pode vazar a representação Python de um enum ("SentidoViagem.IDA")."""

import pytest

pytestmark = pytest.mark.integration


def test_horarios_da_rota_serializam_sentido_como_valor(gestor, rota, horario_rota):
    resp = gestor.client.get(f"/v1/rotas/{rota.id}/horarios")

    assert resp.status_code == 200
    assert "SentidoViagem." not in resp.get_data(as_text=True)
    assert resp.get_json()["items"][0]["sentido"] == horario_rota.sentido.value


def test_detalhe_da_rota_nao_vaza_enum(gestor, rota, horario_rota):
    resp = gestor.client.get(f"/v1/rotas/{rota.id}")

    assert resp.status_code == 200
    assert "SentidoViagem." not in resp.get_data(as_text=True)


def test_listas_de_viagem_nao_vazam_enum(gestor, motorista, viagem_futura_agendada_com_motorista):
    for client, url in (
        (gestor.client, "/v1/viagens/"),
        (motorista.client, "/v1/viagens/minhas"),
    ):
        resp = client.get(url)
        assert resp.status_code == 200, url
        corpo = resp.get_data(as_text=True)
        assert "SentidoViagem." not in corpo, url
        assert "StatusViagem." not in corpo, url
