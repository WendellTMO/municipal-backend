"""Trocar a senha logado: senha atual, regras da senha nova, trava, sessões antigas e aviso."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from app.models.notificacao import Notificacao
from app.models.password_reset import PasswordResetToken
from app.models.user import User

ATUAL = "StrongPass123!"
NOVA = "cavalo-lilas-tijolo-87"


@pytest.fixture(autouse=True)
def sem_rede():
    """Nenhum teste daqui consulta a internet nem manda e-mail de verdade."""
    with (
        patch("app.utils.senha_segura.senha_vazada", return_value=False) as vazada,
        patch("app.services.auth_service.send_email") as email,
    ):
        vazada.email = email
        yield vazada


def _trocar(actor, atual=ATUAL, nova=NOVA, confirmacao=None):
    return actor.client.post(
        "/v1/auth/change-password",
        json={
            "current_password": atual,
            "new_password": nova,
            "confirm_password": nova if confirmacao is None else confirmacao,
        },
    )


def test_troca_a_senha_e_o_login_passa_a_aceitar_so_a_nova(client, aluno, _db):
    r = _trocar(aluno)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["token"]

    antiga = client.post("/v1/auth/login", json={"email": aluno.user.email, "password": ATUAL})
    nova = client.post("/v1/auth/login", json={"email": aluno.user.email, "password": NOVA})
    assert antiga.status_code == 401
    assert nova.status_code == 200


def test_avisa_o_dono_por_notificacao_e_por_email(aluno, sem_rede, _db):
    assert _trocar(aluno).status_code == 200

    aviso = Notificacao.query.filter_by(usuario_id=aluno.user.id, titulo="Senha alterada").one()
    assert "não foi você" in aviso.mensagem
    sem_rede.email.assert_called_once()
    assert sem_rede.email.call_args.kwargs["to"] == aluno.user.email


def test_senha_atual_errada_e_recusada_e_nao_troca(aluno, _db):
    r = _trocar(aluno, atual="errada-errada")
    assert r.status_code == 400
    assert "senha atual" in r.get_json()["error"]["message"].lower()


def test_cinco_erros_seguidos_travam_a_troca_ate_com_a_senha_certa(aluno, _db):
    for _ in range(5):
        assert _trocar(aluno, atual="errada-errada").status_code == 400

    travada = _trocar(aluno)  # senha atual certa, mas já travou
    assert travada.status_code == 429

    usuario = _db.session.get(User, aluno.user.id)
    usuario.troca_senha_bloqueada_ate = datetime.now(UTC) - timedelta(seconds=1)
    _db.session.commit()
    assert _trocar(aluno).status_code == 200


def test_acerto_zera_a_contagem_de_erros(aluno, _db):
    for _ in range(4):
        _trocar(aluno, atual="errada-errada")
    assert _trocar(aluno).status_code == 200
    assert _db.session.get(User, aluno.user.id).falhas_troca_senha == 0


@pytest.mark.parametrize(
    "nova,confirmacao,trecho",
    [
        ("curta1", "curta1", "mínimo"),
        ("a" * 129, "a" * 129, "máximo"),
        (NOVA, NOVA + "x", "coincidem"),
        (ATUAL, ATUAL, "diferente da atual"),
        ("senha123", "senha123", "muito comum"),
        ("aaaaaaaaaaaa", "aaaaaaaaaaaa", "muito comum"),
    ],
)
def test_regras_da_senha_nova(aluno, nova, confirmacao, trecho):
    r = _trocar(aluno, nova=nova, confirmacao=confirmacao)
    assert r.status_code == 400
    assert trecho in r.get_json()["error"]["message"]


def test_recusa_senha_com_o_email_do_usuario(aluno):
    parte = aluno.user.email.split("@")[0]
    r = _trocar(aluno, nova=f"{parte}-2026-x")
    assert r.status_code == 400
    assert "e-mail" in r.get_json()["error"]["message"]


def test_recusa_senha_que_ja_vazou(aluno, sem_rede):
    sem_rede.return_value = True
    r = _trocar(aluno)
    assert r.status_code == 400
    assert "vazamentos" in r.get_json()["error"]["message"]


def test_sem_token_nao_troca(client):
    r = client.post(
        "/v1/auth/change-password",
        json={"current_password": ATUAL, "new_password": NOVA, "confirm_password": NOVA},
    )
    assert r.status_code == 401


def test_sessao_antiga_deixa_de_valer_e_o_token_novo_vale(client, app, aluno):
    with app.app_context():
        antigo = create_access_token(identity=str(aluno.user.id))
    time.sleep(1.1)  # o token novo precisa nascer em outro segundo

    novo = _trocar(aluno).get_json()["token"]

    com_antigo = client.get("/v1/notificacoes", headers={"Authorization": f"Bearer {antigo}"})
    com_novo = client.get("/v1/notificacoes", headers={"Authorization": f"Bearer {novo}"})
    assert com_antigo.status_code == 401
    assert com_antigo.get_json()["error"]["code"] == "TOKEN_REVOKED"
    assert com_novo.status_code == 200


def test_apaga_links_de_recuperacao_pendentes(aluno, _db):
    _db.session.add(
        PasswordResetToken(
            user_id=aluno.user.id, token="t" * 20, expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
    )
    _db.session.commit()

    assert _trocar(aluno).status_code == 200
    assert PasswordResetToken.query.filter_by(user_id=aluno.user.id).count() == 0


def test_falha_no_email_nao_desfaz_a_troca(client, aluno, sem_rede):
    sem_rede.email.side_effect = RuntimeError("smtp fora")
    assert _trocar(aluno).status_code == 200
    ok = client.post("/v1/auth/login", json={"email": aluno.user.email, "password": NOVA})
    assert ok.status_code == 200


def test_redefinir_senha_pelo_email_tambem_derruba_as_sessoes(client, app, aluno, _db):
    with app.app_context():
        antigo = create_access_token(identity=str(aluno.user.id))
    time.sleep(1.1)
    _db.session.add(
        PasswordResetToken(
            user_id=aluno.user.id, token="r" * 20, expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
    )
    _db.session.commit()

    client.post(
        "/v1/auth/reset-password",
        json={"token": "r" * 20, "new_password": NOVA, "confirm_password": NOVA},
    )

    r = client.get("/v1/notificacoes", headers={"Authorization": f"Bearer {antigo}"})
    assert r.status_code == 401
