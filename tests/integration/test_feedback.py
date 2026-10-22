import pytest

from app.models.base import db
from app.models.enum import TipoFeedback
from app.models.feedback import Feedback

MENSAGEM = "O botao de confirmar presenca nao responde"


def _post(client, **overrides):
    body = {"tipo": "BUG", "mensagem": MENSAGEM}
    body.update(overrides)
    return client.post("/v1/feedback", json=body)


@pytest.mark.integration
def test_feedback_sucesso_grava_usuario_e_prefeitura_do_token(aluno, prefeitura):
    r = _post(
        aluno.client,
        tela="Agenda",
        versao_app="1.2.3",
        plataforma="android",
        usuario_id="00000000-0000-0000-0000-000000000000",
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    assert body["message"] == "Feedback registrado"

    row = db.session.get(Feedback, body["id"])
    assert row.usuario_id == aluno.user.id
    assert row.prefeitura_id == prefeitura.id
    assert row.tipo == TipoFeedback.BUG
    assert row.mensagem == MENSAGEM
    assert row.tela == "Agenda"
    assert row.versao_app == "1.2.3"
    assert row.plataforma == "android"
    assert row.created_at is not None


@pytest.mark.integration
def test_feedback_campos_opcionais_ausentes_ou_nulos_viram_null(aluno):
    r = _post(aluno.client, tipo="SUGESTAO", tela=None)
    assert r.status_code == 201, r.get_data(as_text=True)

    row = db.session.get(Feedback, r.get_json()["id"])
    assert row.tela is None
    assert row.versao_app is None
    assert row.plataforma is None


@pytest.mark.integration
def test_feedback_mensagem_recebe_strip(aluno):
    r = _post(aluno.client, mensagem="   " + MENSAGEM + "  \n")
    assert r.status_code == 201
    assert db.session.get(Feedback, r.get_json()["id"]).mensagem == MENSAGEM


@pytest.mark.integration
def test_feedback_tipo_invalido_retorna_400(aluno):
    assert _post(aluno.client, tipo="ELOGIO").status_code == 400


@pytest.mark.integration
def test_feedback_sem_tipo_retorna_400(aluno):
    r = aluno.client.post("/v1/feedback", json={"mensagem": MENSAGEM})
    assert r.status_code == 400


@pytest.mark.integration
def test_feedback_mensagem_curta_retorna_400(aluno):
    assert _post(aluno.client, mensagem="curta").status_code == 400


@pytest.mark.integration
def test_feedback_mensagem_so_espacos_retorna_400(aluno):
    assert _post(aluno.client, mensagem=" " * 30).status_code == 400


@pytest.mark.integration
def test_feedback_mensagem_longa_retorna_400(aluno):
    assert _post(aluno.client, mensagem="a" * 2001).status_code == 400


@pytest.mark.integration
def test_feedback_mensagem_no_limite_de_2000_passa(aluno):
    assert _post(aluno.client, mensagem="a" * 2000).status_code == 201


@pytest.mark.integration
def test_feedback_plataforma_invalida_retorna_400(aluno):
    assert _post(aluno.client, plataforma="windows").status_code == 400


@pytest.mark.integration
def test_feedback_sem_token_retorna_401(client):
    r = _post(client)
    assert r.status_code == 401


@pytest.mark.integration
def test_feedback_user_agent_e_truncado(aluno):
    r = aluno.client.post(
        "/v1/feedback",
        json={"tipo": "DUVIDA", "mensagem": MENSAGEM},
        headers={"User-Agent": "x" * 500},
    )
    assert r.status_code == 201
    row = db.session.get(Feedback, r.get_json()["id"])
    assert row.user_agent == "x" * 300
