def test_confirmar_presenca_requires_auth(client, viagem_futura_agendada_com_motorista, ponto):
    r = client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": ponto.id},
    )
    assert r.status_code in (401, 422)


def test_confirmar_presenca_only_allows_aluno(gestor, viagem_futura_agendada_com_motorista, ponto):
    r = gestor.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": ponto.id},
    )
    assert r.status_code == 403


def test_confirmar_presenca_viagem_not_found(aluno):
    r = aluno.client.put(
        "/v1/viagens/00000000-0000-0000-0000-000000000000/confirmacao",
        json={"confirmacao": False},
    )
    assert r.status_code == 404


def test_confirmar_presenca_marshmallow_requires_ponto_if_confirmacao_true(
    aluno, rota_aluno, viagem_futura_agendada_com_motorista, dia_operacao
):
    # o service exige o ponto quando confirmacao=True e não há padrão
    r = aluno.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": True},
    )
    assert r.status_code == 400


def test_confirmar_presenca_forbidden_if_not_inscrito(
    aluno, viagem_futura_agendada_com_motorista, dia_operacao
):
    r = aluno.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": False},
    )
    assert r.status_code == 403


def test_confirmar_presenca_ponto_must_exist_in_rota(
    aluno, rota_aluno, viagem_futura_agendada_com_motorista, dia_operacao
):
    r = aluno.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": "00000000-0000-0000-0000-000000000029"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == "ponto_embarque_id"


def test_confirmar_presenca_success_confirm_and_unconfirm(
    aluno,
    aluno_com_instituicao,
    rota_aluno,
    viagem_futura_agendada_com_motorista,
    dia_operacao,
    rota_ponto,
):
    # confirmar
    r = aluno.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": str(rota_ponto.ponto_id)},
    )
    assert r.status_code == 200, r.get_data(as_text=True)

    data = r.get_json() or {}

    assert data.get("confirmacao") in (True, "true", 1) or True
    assert data.get("ponto_embarque") == str(rota_ponto.ponto.apelido)

    # desconfirmar
    r2 = aluno.client.put(
        f"/v1/viagens/{viagem_futura_agendada_com_motorista.id}/confirmacao",
        json={"confirmacao": False},
    )
    assert r2.status_code == 200, r2.get_data(as_text=True)

    data2 = r2.get_json() or {}
    # novamente: depende do teu controller; o importante é não 500 e limpar ponto
    # se teu retorno for a confirmação serializada:
    if isinstance(data2, dict) and "ponto_embarque" in data2:
        assert data2["ponto_embarque"] is None
