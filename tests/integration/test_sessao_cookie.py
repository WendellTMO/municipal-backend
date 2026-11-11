import pytest

SENHA = "StrongPass123!"
COM_COOKIE = {"X-Sessao-Cookie": "1"}


def _login(client, gestor, headers=None):
    return client.post(
        "/v1/auth/login",
        json={"email": gestor.user.email, "password": SENHA},
        headers=headers or {},
    )


def _cookies_da_resposta(resposta):
    return [c for c in resposta.headers.getlist("Set-Cookie")]


@pytest.mark.integration
def test_login_sem_cabecalho_segue_igual_para_o_app(client, gestor):
    r = _login(client, gestor)
    assert r.status_code == 200
    assert r.get_json()["token"]
    assert _cookies_da_resposta(r) == []


@pytest.mark.integration
def test_login_do_site_poe_token_em_cookie_httponly_e_tira_do_corpo(client, gestor):
    r = _login(client, gestor, COM_COOKIE)
    assert r.status_code == 200
    assert "token" not in r.get_json()
    assert r.get_json()["user"]["id"] == str(gestor.user.id)
    acesso = [c for c in _cookies_da_resposta(r) if c.startswith("access_token_cookie=")]
    assert len(acesso) == 1
    assert "HttpOnly" in acesso[0]
    assert "SameSite=Strict" in acesso[0]
    # O cookie de CSRF precisa ser legível pelo JavaScript: sem HttpOnly.
    csrf = [c for c in _cookies_da_resposta(r) if c.startswith("csrf_access_token=")]
    assert len(csrf) == 1
    assert "HttpOnly" not in csrf[0]


@pytest.mark.integration
def test_leitura_com_so_o_cookie_funciona(client, gestor):
    _login(client, gestor, COM_COOKIE)
    r = client.get("/v1/users/me")
    assert r.status_code == 200
    assert r.get_json()["id"] == str(gestor.user.id)


@pytest.mark.integration
def test_escrita_com_cookie_sem_csrf_e_recusada(client, gestor):
    _login(client, gestor, COM_COOKIE)
    r = client.post(
        "/v1/users/change-password",
        json={
            "current_password": SENHA,
            "new_password": "OutraSenha456!",
            "confirm_password": "OutraSenha456!",
        },
    )
    assert r.status_code == 401, r.get_data(as_text=True)


@pytest.mark.integration
def test_escrita_com_cookie_e_csrf_funciona_e_renova_o_cookie(client, gestor):
    r = _login(client, gestor, COM_COOKIE)
    csrf = client.get_cookie("csrf_access_token").value
    r = client.post(
        "/v1/users/change-password",
        json={
            "current_password": SENHA,
            "new_password": "OutraSenha456!",
            "confirm_password": "OutraSenha456!",
        },
        headers={"X-CSRF-TOKEN": csrf, **COM_COOKIE},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "token" not in r.get_json()
    assert any(c.startswith("access_token_cookie=") for c in _cookies_da_resposta(r))


@pytest.mark.integration
def test_token_no_cabecalho_nao_exige_csrf(client, gestor):
    token = _login(client, gestor).get_json()["token"]
    r = client.post(
        "/v1/users/change-password",
        json={
            "current_password": SENHA,
            "new_password": "OutraSenha456!",
            "confirm_password": "OutraSenha456!",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)


@pytest.mark.integration
def test_logout_apaga_o_cookie_e_a_sessao_cai(client, gestor):
    _login(client, gestor, COM_COOKIE)
    r = client.post("/v1/auth/logout")
    assert r.status_code == 200
    apagados = [c for c in _cookies_da_resposta(r) if c.startswith("access_token_cookie=;")]
    assert len(apagados) == 1
    assert client.get("/v1/users/me").status_code == 401
