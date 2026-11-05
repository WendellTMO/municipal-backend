"""Authentication service - login and password recovery."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash

from app.core.exceptions import (
    ForbiddenError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
)
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import UserRole, UserStatus
from app.models.password_reset import PasswordResetToken
from app.models.user import Aluno, User
from app.services.notificacao_service import NotificacaoService
from app.utils import audit_logger, validate_email, validate_password
from app.utils.email_sender import send_email
from app.utils.email_template import montar_email_html
from app.utils.senha_segura import validar_senha_nova

logger = logging.getLogger(__name__)


def login_user(data: dict[str, Any]) -> dict[str, Any]:
    """
    Authenticate user and return JWT token.

    Args:
        data: Login credentials (email and password)

    Returns:
        dict with token and user info

    Raises:
        UnauthorizedError: If credentials are invalid
        ValidationError: If input data is invalid
    """
    email = data.get("email", "").strip()
    password = data.get("password")

    if not email or not password:
        audit_logger.log_auth(
            action="login_attempt",
            email=email or "unknown",
            success=False,
            details={"reason": "missing_credentials"},
        )
        raise UnauthorizedError("Credenciais inválidas")
    try:
        email = validate_email(email)
    except ValidationError:
        audit_logger.log_auth(
            action="login_attempt",
            email=email,
            success=False,
            details={"reason": "invalid_email_format"},
        )
        raise UnauthorizedError("Credenciais inválidas")

    user = User.query.filter_by(email=email).first()

    if not user:
        audit_logger.log_auth(
            action="login_attempt",
            email=email,
            success=False,
            details={"reason": "user_not_found"},
        )
        logger.info(f"Login attempt for non-existent user: {email}")
        raise UnauthorizedError("Credenciais inválidas")

    if not check_password_hash(user.senha_hash, password):
        audit_logger.log_auth(
            action="login_attempt",
            user_id=str(user.id),
            email=email,
            success=False,
            details={"reason": "invalid_password"},
        )
        logger.warning(f"Failed login attempt for user {user.id}: invalid password")
        raise UnauthorizedError("Credenciais inválidas")

    # Block disabled accounts
    if hasattr(user, "status") and user.status == UserStatus.DISABLED:
        audit_logger.log_auth(
            action="login_attempt",
            user_id=str(user.id),
            email=email,
            success=False,
            details={"reason": "account_disabled"},
        )
        raise ForbiddenError("Sua conta está desativada. Entre em contato com o gestor municipal.")

    # Block minors whose guardian has not yet consented
    if (
        user.role == UserRole.ALUNO
        and hasattr(user, "status")
        and user.status == UserStatus.PENDING_SIGNUP
    ):
        aluno = Aluno.query.get(str(user.id))
        if aluno and aluno.email_responsavel and not aluno.guardian_consented_at:
            audit_logger.log_auth(
                action="login_attempt",
                user_id=str(user.id),
                email=email,
                success=False,
                details={"reason": "pending_guardian_consent"},
            )
            raise ForbiddenError(
                f"Seu cadastro aguarda a confirmação do responsável legal. "
                f"Um e-mail foi enviado para {aluno.email_responsavel}."
            )

    access_token = create_access_token(
        identity=str(user.id), additional_claims={"role": str(user.role)}
    )

    # Log successful login
    audit_logger.log_auth(
        action="login",
        user_id=str(user.id),
        email=email,
        success=True,
        details={"role": str(user.role)},
    )
    logger.info(f"User {user.id} logged in successfully")

    return {
        "message": "Login successful",
        "token": access_token,
        "user": {
            "id": str(user.id),
            "nome": user.nome,
            "email": user.email,
            "role": str(user.role),
        },
    }


def request_password_reset(email_raw: str, base_url: str) -> None:
    """
    Send password recovery email with link if the user exists.
    Always returns without error (does not reveal if email exists).
    Raises only on validation or mail delivery failure.
    """
    try:
        email = validate_email(email_raw.strip())
    except ValidationError:
        raise ValidationError("Formato de email inválido")

    user = User.query.filter_by(email=email).first()
    if not user:
        logger.info("Password reset requested for unknown email: %s", email)
        return

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    reset_record = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at)
    with transactional():
        db.session.add(reset_record)

    link = f"{base_url.rstrip('/')}/redefinir-senha/{token}"
    subject = "Recuperação de senha - BusKá"
    body_plain = (
        f"Olá, {user.nome}.\n\n"
        "Você solicitou a recuperação de senha no BusKá.\n\n"
        f"Acesse o link abaixo para redefinir sua senha (válido por 1 hora):\n{link}\n\n"
        "Se não foi você, ignore este e-mail.\n\n"
        "Equipe BusKá"
    )
    body_html = montar_email_html(
        titulo="Recuperação de senha",
        preheader="Use o link para redefinir sua senha do BusKá. Ele vale por 1 hora.",
        saudacao=f"Olá, {user.nome}.",
        paragrafos=["Você solicitou a recuperação de senha no BusKá."],
        botao_texto="Redefinir senha",
        botao_url=link,
        validade="O link é válido por 1 hora. Se não foi você, ignore este e-mail.",
    )
    send_email(
        to=email,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        logo_inline=True,
    )


def reset_password(token: str, new_password: str) -> None:
    """Reset user password using a valid token. Invalidates the token."""
    record = PasswordResetToken.query.filter_by(token=token).first()
    if not record:
        raise ValidationError("Link inválido ou expirado")
    if record.is_expired():
        # O delete fica fora do `raise`: com o `transactional()` envolvendo os
        # dois, o rollback desfaria a remoção do token expirado.
        with transactional():
            db.session.delete(record)
        raise ValidationError("Link expirado. Solicite uma nova recuperação de senha.")

    new_password = validate_password(new_password, "Nova senha")
    user = db.session.get(User, record.user_id)
    if not user:
        # Ramo inalcançável hoje: a FK do token é ON DELETE CASCADE, então não
        # existe token cujo usuário sumiu. Mantido porque é o estreitamento de
        # tipo que o mypy exige, e trocá-lo por um cast seria pior.
        with transactional():
            db.session.delete(record)
        raise ValidationError("Link inválido")

    with transactional():
        user.senha_hash = generate_password_hash(new_password)
        user.senha_alterada_em = datetime.now(UTC)
        db.session.delete(record)
    logger.info("Password reset completed for user %s", user.id)


# Erros seguidos da senha atual antes de travar a troca, e por quanto tempo.
MAX_FALHAS_TROCA_SENHA = 5
BLOQUEIO_TROCA_SENHA = timedelta(minutes=15)


def alterar_senha(user_id: str, senha_atual: str, nova_senha: str, confirmacao: str) -> dict[str, Any]:
    """Troca a senha de quem já está logado.

    Pede a senha atual (quem pegou um celular desbloqueado não troca a senha), trava depois de
    5 erros seguidos, aplica as regras de senha nova, derruba as outras sessões, apaga links de
    recuperação pendentes e avisa o dono por notificação e e-mail. Devolve um token novo, para o
    aparelho que trocou a senha continuar logado.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise UnauthorizedError("Não autenticado")
    if user.status == UserStatus.DISABLED:
        raise ForbiddenError("Sua conta está desativada. Entre em contato com o gestor municipal.")

    agora = datetime.now(UTC)
    if user.troca_senha_bloqueada_ate and user.troca_senha_bloqueada_ate > agora:
        minutos = max(1, int((user.troca_senha_bloqueada_ate - agora).total_seconds() // 60) + 1)
        raise RateLimitError(f"Muitas tentativas. Tente de novo em {minutos} minutos.")

    if not senha_atual or not check_password_hash(user.senha_hash, senha_atual):
        _registrar_falha_troca_senha(user, agora)
        raise ValidationError("A senha atual está incorreta")

    if not nova_senha or nova_senha != confirmacao:
        raise ValidationError("As senhas não coincidem")
    if check_password_hash(user.senha_hash, nova_senha):
        raise ValidationError("A nova senha precisa ser diferente da atual")
    nova_senha = validar_senha_nova(nova_senha, email=user.email, nome=user.nome)

    with transactional():
        user.senha_hash = generate_password_hash(nova_senha)
        user.senha_alterada_em = agora
        user.falhas_troca_senha = 0
        user.troca_senha_bloqueada_ate = None
        PasswordResetToken.query.filter_by(user_id=user.id).delete()
        NotificacaoService._criar_notificacao_interna(
            usuario_id=str(user.id),
            titulo="Senha alterada",
            mensagem="A senha da sua conta foi alterada. Se não foi você, recupere sua conta agora.",
        )

    audit_logger.log_auth(
        action="password_change", user_id=str(user.id), email=user.email, success=True
    )
    _avisar_troca_de_senha_por_email(user, agora)
    token = create_access_token(identity=str(user.id), additional_claims={"role": str(user.role)})
    return {"message": "Senha alterada com sucesso.", "token": token}


def _registrar_falha_troca_senha(user: User, agora: datetime) -> None:
    """Soma a falha e trava a troca na quinta seguida. Fica gravado mesmo com o erro que vem depois."""
    with transactional():
        user.falhas_troca_senha = (user.falhas_troca_senha or 0) + 1
        if user.falhas_troca_senha >= MAX_FALHAS_TROCA_SENHA:
            user.troca_senha_bloqueada_ate = agora + BLOQUEIO_TROCA_SENHA
            user.falhas_troca_senha = 0
    audit_logger.log_auth(
        action="password_change",
        user_id=str(user.id),
        email=user.email,
        success=False,
        details={"reason": "invalid_current_password"},
    )


def _avisar_troca_de_senha_por_email(user: User, quando: datetime) -> None:
    """E-mail de segurança: quem não trocou a senha precisa saber na hora. Falha de envio não desfaz a troca."""
    hora = quando.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y às %H:%M")
    try:
        send_email(
            to=user.email,
            subject="Sua senha do BusKá foi alterada",
            body_plain=(
                f"Olá, {user.nome}.\n\n"
                f"A senha da sua conta no BusKá foi alterada em {hora}.\n\n"
                "Se foi você, não precisa fazer nada. Se não foi, use \"Esqueci a senha\" na tela de "
                "entrada para criar uma nova e avise o gestor municipal.\n\n"
                "Equipe BusKá"
            ),
            body_html=montar_email_html(
                titulo="Sua senha foi alterada",
                preheader="A senha da sua conta do BusKá mudou.",
                saudacao=f"Olá, {user.nome}.",
                paragrafos=[
                    f"A senha da sua conta no BusKá foi alterada em {hora}.",
                    "Se foi você, não precisa fazer nada. Se não foi, use "
                    "\"Esqueci a senha\" na tela de entrada para criar uma nova e avise o gestor municipal.",
                ],
                botao_texto="Abrir o BusKá",
                botao_url=(current_app.config.get("FRONTEND_URL") or "https://buska.lsd.ufcg.edu.br"),
            ),
            logo_inline=True,
        )
    except Exception:
        logger.exception("Não foi possível enviar o e-mail de senha alterada para %s", user.id)
