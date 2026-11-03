def test_controlar_viagem_requires_auth(client, viagem_futura_agendada_com_motorista):
    r = client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/acao",
        json={"acao": "INICIAR"},
    )
    assert r.status_code in (401, 422)


def test_controlar_viagem_invalid_action_400(motorista, viagem_futura_agendada_com_motorista):
    r = motorista.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/acao",
        json={"acao": "BLA"},
    )
    assert r.status_code == 400


def test_controlar_viagem_viagem_not_found(motorista):
    r = motorista.client.put(
        "/v1/viagens/00000000-0000-0000-0000-000000000000/acao",
        json={"acao": "INICIAR"},
    )
    assert r.status_code == 404


def test_controlar_viagem_iniciar_success(motorista, viagem_futura_agendada_com_motorista):
    r = motorista.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/acao",
        json={"acao": "INICIAR"},
    )
    assert r.status_code == 200

    assert r.get_json()["status"] == "EM_ANDAMENTO"
    assert r.get_json()["inicio_real"] is not None
    assert r.get_json()["horario_fim"] is None


def test_controlar_viagem_finalizar_success(motorista, viagem_futura_iniciada_com_motorista):
    r = motorista.client.put(
        f"/v1/viagens/{viagem_futura_iniciada_com_motorista.id}/acao",
        json={"acao": "FINALIZAR"},
    )
    assert r.status_code == 200

    assert r.get_json()["status"] == "FINALIZADA"
    assert r.get_json()["horario_fim"] is not None
    assert r.get_json()["km_real"] == 0.0  # sem telemetria, a distância é zero
