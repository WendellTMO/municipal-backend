"""Trava de login por e-mail com espera exponencial."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.login_tentativa import LoginTentativa
from app.services.login_guard import espera_em_segundos

SENHA = "StrongPass123!"


def _entrar(client, email, senha):
    return client.post("/v1/auth/login", json={"email": email, "password": senha})


def _errar(client, email, vezes):
    for _ in range(vezes):
        assert _entrar(client, email, "errada-errada").status_code == 401


def _destravar(_db, email):
    registro = _db.session.get(LoginTentativa, email.lower())
    registro.bloqueado_ate = datetime.now(UTC) - timedelta(seconds=1)
    _db.session.commit()


def test_espera_dobra_a_cada_falha_ate_o_teto():
    assert [espera_em_segundos(n) for n in range(1, 11)] == [0, 0, 0, 0, 30, 60, 120, 240, 480, 900]
    assert espera_em_segundos(500) == 900


def test_quatro_erros_nao_travam_e_o_quinto_trava_ate_a_senha_certa(client, aluno, _db):
    email = aluno.user.email
    _errar(client, email, 4)
    assert _entrar(client, email, SENHA).status_code == 200  # ainda não travou

    _errar(client, email, 5)
    travado = _entrar(client, email, SENHA)  # senha certa, mas travado
    assert travado.status_code == 429
    assert "Muitas tentativas" in travado.get_json()["error"]["message"]


def test_cada_falha_depois_do_limite_dobra_a_espera(client, aluno, _db):
    email = aluno.user.email
    _errar(client, email, 5)
    primeira = _db.session.get(LoginTentativa, email.lower())
    assert 25 <= (primeira.bloqueado_ate - datetime.now(UTC)).total_seconds() <= 30

    _destravar(_db, email)
    assert _entrar(client, email, "errada-errada").status_code == 401  # 6ª falha
    _db.session.expire_all()
    segunda = _db.session.get(LoginTentativa, email.lower())
    assert 55 <= (segunda.bloqueado_ate - datetime.now(UTC)).total_seconds() <= 60


def test_tentativa_durante_a_trava_nao_conta(client, aluno, _db):
    email = aluno.user.email
    _errar(client, email, 5)
    for _ in range(3):
        assert _entrar(client, email, "errada-errada").status_code == 429
    _db.session.expire_all()
    assert _db.session.get(LoginTentativa, email.lower()).falhas == 5


def test_login_certo_zera_a_contagem(client, aluno, _db):
    email = aluno.user.email
    _errar(client, email, 3)
    assert _entrar(client, email, SENHA).status_code == 200
    _db.session.expire_all()
    assert _db.session.get(LoginTentativa, email.lower()) is None


def test_email_que_nao_existe_trava_igual_e_responde_igual(client):
    email = "ninguem@buska.test"
    _errar(client, email, 5)
    assert _entrar(client, email, "qualquer-coisa").status_code == 429


def test_trava_de_um_email_nao_atinge_outro(client, aluno, gestor, _db):
    _errar(client, aluno.user.email, 5)
    assert _entrar(client, gestor.user.email, SENHA).status_code == 200


def test_contagem_antiga_recomeca(client, aluno, _db):
    email = aluno.user.email
    _errar(client, email, 3)
    registro = _db.session.get(LoginTentativa, email.lower())
    registro.atualizado_em = datetime.now(UTC) - timedelta(days=2)
    _db.session.commit()

    _errar(client, email, 1)
    _db.session.expire_all()
    assert _db.session.get(LoginTentativa, email.lower()).falhas == 1
