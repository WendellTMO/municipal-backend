import pytest


@pytest.mark.integration
def test_login_missing_fields_returns_400(client):
    r = client.post("/v1/auth/login", json={})
    assert r.status_code == 400, r.get_data(as_text=True)
    data = r.get_json() or {}
    assert "error" in data


@pytest.mark.integration
def test_login_invalid_credentials_returns_401(client):
    r = client.post("/v1/auth/login", json={"email": "nope@buska.test", "password": "wrong"})
    assert r.status_code == 401, r.get_data(as_text=True)


@pytest.mark.integration
def test_login_success_returns_token(client, gestor):
    r = client.post(
        "/v1/auth/login", json={"email": gestor.user.email, "password": "StrongPass123!"}
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json() or {}
    assert data.get("token"), f"Token not found in response: {data}"
    assert data.get("user"), f"User not found in response: {data}"
    assert data.get("user").get("id") == str(
        gestor.user.id
    ), f"User ID mismatch: {data.get('user')}"
    assert (
        data.get("user").get("email") == gestor.user.email
    ), f"User email mismatch: {data.get('user')}"
    assert (
        data.get("user").get("nome") == gestor.user.nome
    ), f"User name mismatch: {data.get('user')}"
    assert data["user"]["role"] == gestor.user.role.value, f"User role mismatch: {data.get('user')}"


def _token_reset(_db, user_id):
    from datetime import UTC, datetime, timedelta

    from app.models.password_reset import PasswordResetToken

    registro = PasswordResetToken(
        user_id=user_id, token="tok-pagina", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro.token


@pytest.mark.integration
def test_reset_nao_serve_mais_pagina_html(client):
    # A tela de redefinir senha é do app (/redefinir-senha/<token>); a API só recebe o POST.
    assert client.get("/v1/auth/reset-password?token=abc").status_code == 405


@pytest.mark.integration
def test_reset_post_senha_curta_400_json(client, aluno, _db):
    token = _token_reset(_db, aluno.user.id)
    r = client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "123", "confirm_password": "123"},
    )
    assert r.status_code == 400
    assert "error" in r.get_json()


@pytest.mark.integration
def test_reset_post_senhas_diferentes_400_json(client, aluno, _db):
    token = _token_reset(_db, aluno.user.id)
    r = client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "NovaSenha123!", "confirm_password": "Outra123!"},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_reset_post_json_preserva_resposta_json(client, aluno, _db):
    token = _token_reset(_db, aluno.user.id)
    r = client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "NovaSenha123!", "confirm_password": "NovaSenha123!"},
    )
    assert r.status_code == 200
    assert "message" in r.get_json()


@pytest.mark.integration
def test_reset_post_json_token_invalido_400_json(client):
    r = client.post(
        "/v1/auth/reset-password",
        json={
            "token": "nope",
            "new_password": "NovaSenha123!",
            "confirm_password": "NovaSenha123!",
        },
    )
    assert r.status_code == 400
    assert "error" in r.get_json()
