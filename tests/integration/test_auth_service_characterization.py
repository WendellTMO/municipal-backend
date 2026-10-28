"""Characterization tests for ``app/services/auth_service.py``.

Purpose: pin the CURRENT observable behaviour of every public function in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests: where the behaviour pinned here is a known
bug, the test name and comment say so. If one of these tests changes in
the SAME PR that changes the behaviour of
`auth_service.py`, the change was not a refactor.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ForbiddenError, UnauthorizedError, ValidationError
from app.models.enum import UserStatus
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services import auth_service
from app.services.auth_service import login_user, request_password_reset, reset_password

pytestmark = pytest.mark.integration

SENHA = "StrongPass123!"


# ─── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture()
def emails_enviados(monkeypatch):
    """Captura as chamadas de `send_email` sem sair da máquina."""
    capturados = []
    monkeypatch.setattr(
        auth_service,
        "send_email",
        lambda **kwargs: capturados.append(kwargs),
    )
    return capturados


def _token_de_reset(_db, user_id, horas=1):
    registro = PasswordResetToken(
        user_id=user_id,
        token=f"tok-{user_id}-{horas}",
        expires_at=datetime.now(UTC) + timedelta(hours=horas),
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


# ─── login_user: credenciais recusadas ──────────────────────────────────────


def test_login_sem_email_401(_db):
    with pytest.raises(UnauthorizedError) as exc:
        login_user({"password": SENHA})

    assert str(exc.value) == "Credenciais inválidas"
    assert exc.value.status_code == 401


def test_login_sem_senha_401(_db, aluno):
    with pytest.raises(UnauthorizedError) as exc:
        login_user({"email": aluno.user.email})

    assert str(exc.value) == "Credenciais inválidas"


def test_login_payload_vazio_401(_db):
    with pytest.raises(UnauthorizedError):
        login_user({})


def test_login_email_com_formato_invalido_401(_db):
    # Formato inválido recebe a mesma mensagem de credencial errada, sem
    # revelar que o problema foi o formato.
    with pytest.raises(UnauthorizedError) as exc:
        login_user({"email": "isso-nao-e-email", "password": SENHA})

    assert str(exc.value) == "Credenciais inválidas"


def test_login_usuario_inexistente_401(_db):
    with pytest.raises(UnauthorizedError) as exc:
        login_user({"email": "ninguem@exemplo.com", "password": SENHA})

    assert str(exc.value) == "Credenciais inválidas"


def test_login_senha_errada_401(_db, aluno):
    with pytest.raises(UnauthorizedError) as exc:
        login_user({"email": aluno.user.email, "password": "SenhaErrada123!"})

    assert str(exc.value) == "Credenciais inválidas"


def test_login_usuario_inexistente_e_senha_errada_dao_a_mesma_resposta(_db, aluno):
    # Enumeração de contas fica fechada: os dois caminhos respondem igual.
    with pytest.raises(UnauthorizedError) as inexistente:
        login_user({"email": "ninguem@exemplo.com", "password": SENHA})
    with pytest.raises(UnauthorizedError) as senha_errada:
        login_user({"email": aluno.user.email, "password": "SenhaErrada123!"})

    assert str(inexistente.value) == str(senha_errada.value)
    assert inexistente.value.status_code == senha_errada.value.status_code


# ─── login_user: caminho feliz ──────────────────────────────────────────────


def test_login_devolve_token_e_dados_do_usuario(_db, aluno):
    resultado = login_user({"email": aluno.user.email, "password": SENHA})

    assert resultado["message"] == "Login successful"
    assert resultado["token"]
    assert resultado["user"] == {
        "id": str(aluno.user.id),
        "nome": aluno.user.nome,
        "email": aluno.user.email,
        "role": str(aluno.user.role),
    }


def test_login_nao_devolve_o_hash_da_senha(_db, aluno):
    resultado = login_user({"email": aluno.user.email, "password": SENHA})

    assert "senha_hash" not in resultado["user"]
    assert aluno.user.senha_hash not in str(resultado)


def test_login_aceita_email_com_espacos_em_volta(_db, gestor):
    resultado = login_user({"email": f"  {gestor.user.email}  ", "password": SENHA})

    assert resultado["user"]["id"] == str(gestor.user.id)


def test_login_funciona_para_gestor_e_motorista(_db, gestor, motorista):
    assert login_user({"email": gestor.user.email, "password": SENHA})["token"]
    assert login_user({"email": motorista.user.email, "password": SENHA})["token"]


# ─── login_user: contas bloqueadas ──────────────────────────────────────────


def test_login_conta_desativada_403(_db, aluno):
    aluno.user.status = UserStatus.DISABLED
    _db.session.commit()

    with pytest.raises(ForbiddenError) as exc:
        login_user({"email": aluno.user.email, "password": SENHA})

    assert str(exc.value) == ("Sua conta está desativada. Entre em contato com o gestor municipal.")
    assert exc.value.status_code == 403


def test_login_desativado_e_checado_depois_da_senha(_db, aluno):
    # Conta desativada com senha errada continua devolvendo 401, não 403: o
    # bloqueio não vira oráculo de existência de conta.
    aluno.user.status = UserStatus.DISABLED
    _db.session.commit()

    with pytest.raises(UnauthorizedError):
        login_user({"email": aluno.user.email, "password": "SenhaErrada123!"})


def test_login_menor_sem_consentimento_do_responsavel_403(_db, aluno):
    aluno.user.status = UserStatus.PENDING_SIGNUP
    aluno.user.email_responsavel = "responsavel@exemplo.com"
    aluno.user.guardian_consented_at = None
    _db.session.commit()

    with pytest.raises(ForbiddenError) as exc:
        login_user({"email": aluno.user.email, "password": SENHA})

    assert "aguarda a confirmação do responsável legal" in str(exc.value)
    assert "responsavel@exemplo.com" in str(exc.value)


def test_login_menor_com_consentimento_registrado_entra(_db, aluno):
    aluno.user.status = UserStatus.PENDING_SIGNUP
    aluno.user.email_responsavel = "responsavel@exemplo.com"
    aluno.user.guardian_consented_at = datetime.now(UTC)
    _db.session.commit()

    assert login_user({"email": aluno.user.email, "password": SENHA})["token"]


def test_login_pendente_sem_email_de_responsavel_entra(_db, aluno):
    # Maior de idade em PENDING_SIGNUP não tem `email_responsavel`, então o
    # bloqueio de consentimento não se aplica e o login passa.
    aluno.user.status = UserStatus.PENDING_SIGNUP
    aluno.user.email_responsavel = None
    _db.session.commit()

    assert login_user({"email": aluno.user.email, "password": SENHA})["token"]


def test_login_gestor_pendente_nao_e_barrado_pelo_guarda_do_aluno(_db, gestor):
    # O guarda de consentimento só olha para ALUNO.
    gestor.user.status = UserStatus.PENDING_SIGNUP
    _db.session.commit()

    assert login_user({"email": gestor.user.email, "password": SENHA})["token"]


# ─── request_password_reset ─────────────────────────────────────────────────


def test_reset_request_email_invalido_400(_db, emails_enviados):
    with pytest.raises(ValidationError) as exc:
        request_password_reset("nao-e-email", "https://app.buska")

    assert str(exc.value) == "Formato de email inválido"
    assert emails_enviados == []


def test_reset_request_email_desconhecido_nao_levanta_e_nao_envia(_db, emails_enviados):
    # Não revela se o e-mail existe: retorna sem erro e sem enviar nada.
    assert request_password_reset("ninguem@exemplo.com", "https://app.buska") is None
    assert emails_enviados == []
    assert PasswordResetToken.query.count() == 0


def test_reset_request_cria_token_e_envia_email(_db, aluno, emails_enviados):
    request_password_reset(aluno.user.email, "https://app.buska")

    registro = PasswordResetToken.query.one()
    assert registro.user_id == aluno.user.id
    assert len(emails_enviados) == 1
    assert emails_enviados[0]["to"] == aluno.user.email
    assert emails_enviados[0]["subject"] == "Recuperação de senha - BusKá"


def test_reset_request_token_expira_em_uma_hora(_db, aluno, emails_enviados):
    antes = datetime.now(UTC)

    request_password_reset(aluno.user.email, "https://app.buska")

    registro = PasswordResetToken.query.one()
    delta = registro.expires_at - antes
    # `antes` é anterior à chamada, então a folga cobre o tempo de execução.
    assert timedelta(minutes=55) < delta < timedelta(hours=1, minutes=5)


def test_reset_request_monta_o_link_com_o_token(_db, aluno, emails_enviados):
    request_password_reset(aluno.user.email, "https://app.buska/")

    registro = PasswordResetToken.query.one()
    esperado = f"https://app.buska/v1/auth/reset-password?token={registro.token}"
    assert esperado in emails_enviados[0]["body_plain"]
    assert esperado in emails_enviados[0]["body_html"]


def test_reset_request_remove_a_barra_final_da_base_url(_db, aluno, emails_enviados):
    request_password_reset(aluno.user.email, "https://app.buska///")

    assert "https://app.buska/v1/auth/" in emails_enviados[0]["body_plain"]
    assert "buska///v1" not in emails_enviados[0]["body_plain"]


def test_reset_request_duas_vezes_gera_dois_tokens_validos(_db, aluno, emails_enviados):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    Cada pedido cria um registro novo sem invalidar os anteriores. Todos os
    links continuam válidos até expirarem, então um link antigo que vazou
    ainda troca a senha.
    """
    request_password_reset(aluno.user.email, "https://app.buska")
    request_password_reset(aluno.user.email, "https://app.buska")

    assert PasswordResetToken.query.count() == 2


# ─── reset_password ─────────────────────────────────────────────────────────


def test_reset_token_inexistente_400(_db):
    with pytest.raises(ValidationError) as exc:
        reset_password("token-que-nao-existe", "NovaSenha123!")

    assert str(exc.value) == "Link inválido ou expirado"


def test_reset_token_expirado_400_e_apaga_o_registro(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id, horas=-1)

    with pytest.raises(ValidationError) as exc:
        reset_password(registro.token, "NovaSenha123!")

    assert str(exc.value) == "Link expirado. Solicite uma nova recuperação de senha."
    assert PasswordResetToken.query.count() == 0


def test_reset_troca_a_senha_e_consome_o_token(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id)
    hash_antigo = aluno.user.senha_hash

    reset_password(registro.token, "NovaSenha123!")

    _db.session.expire_all()
    assert _db.session.get(User, aluno.user.id).senha_hash != hash_antigo
    assert PasswordResetToken.query.count() == 0


def test_reset_permite_login_com_a_senha_nova(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id)
    email = aluno.user.email

    reset_password(registro.token, "NovaSenha123!")

    assert login_user({"email": email, "password": "NovaSenha123!"})["token"]
    with pytest.raises(UnauthorizedError):
        login_user({"email": email, "password": SENHA})


def test_reset_token_e_de_uso_unico(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id)
    token = registro.token

    reset_password(token, "NovaSenha123!")

    with pytest.raises(ValidationError) as exc:
        reset_password(token, "OutraSenha123!")

    assert str(exc.value) == "Link inválido ou expirado"


def test_reset_senha_fraca_400_e_mantem_o_token(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id)

    with pytest.raises(ValidationError):
        reset_password(registro.token, "123")

    # A validação vem depois da checagem de expiração e antes do delete, então
    # o token sobrevive e o usuário pode tentar de novo com uma senha válida.
    assert PasswordResetToken.query.count() == 1


def test_reset_com_usuario_ja_removido_400_e_apaga_o_registro(_db, aluno):
    registro = _token_de_reset(_db, aluno.user.id)
    token = registro.token
    _db.session.delete(aluno.user)
    _db.session.commit()

    # O token cai junto pelo ON DELETE CASCADE do usuário, então o caminho
    # observável é o mesmo do token inexistente.
    #
    # Isto é a prova de que o ramo `if not user` de `reset_password` é código
    # morto: para alcançá-lo seria preciso um token cujo usuário sumiu, e a FK
    # `ON DELETE CASCADE` impede exatamente esse estado. O ramo foi mantido
    # porque é o estreitamento de tipo que o mypy exige.
    with pytest.raises(ValidationError) as exc:
        reset_password(token, "NovaSenha123!")

    assert str(exc.value) == "Link inválido ou expirado"
    assert PasswordResetToken.query.count() == 0


# ─── link de recuperação usa a URL pública ──────────────────────────────────


def test_forgot_password_monta_link_com_frontend_url_e_nao_com_url_root(
    _db, app, client, aluno, emails_enviados
):
    app.config["FRONTEND_URL"] = "https://buska.exemplo.test"
    resposta = client.post("/v1/auth/forgot-password", json={"email": aluno.user.email})

    assert resposta.status_code == 200
    registro = PasswordResetToken.query.one()
    esperado = f"https://buska.exemplo.test/v1/auth/reset-password?token={registro.token}"
    assert esperado in emails_enviados[0]["body_plain"]
    assert f'href="{esperado}"' in emails_enviados[0]["body_html"]


def test_formulario_de_reset_escapa_o_token(client):
    resposta = client.get('/v1/auth/reset-password?token="><script>x</script>')

    corpo = resposta.get_data(as_text=True)
    assert "<script>x</script>" not in corpo
    assert 'action="/v1/auth/reset-password"' in corpo
