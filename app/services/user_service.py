"""User service - CRUD operations, driver creation, password management."""

import logging
from typing import Any, cast

from werkzeug.security import generate_password_hash

from app.core.authz import get_gestor_or_403, get_user_or_404
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import UserRole, UserStatus
from app.models.user import Aluno, Motorista, User
from app.services import auth_service
from app.utils import audit_logger, validate_cpf, validate_email, validate_password

logger = logging.getLogger(__name__)


# Helper functions
def get_all_users(current_user_id: str) -> list[User]:
    """List all users in the same prefeitura (gestor only)."""
    gestor = get_gestor_or_403(current_user_id, "Apenas gestores podem listar usuários")
    return db.session.query(User).filter_by(prefeitura_id=gestor.prefeitura_id).all()


def get_user_by_id(user_id: str, current_user_id: str | None = None) -> User:
    """
    Get user by ID with tenant isolation.
    Users can view themselves, gestores can view users in their prefeitura.
    """
    user = get_user_or_404(user_id)

    # Skip authorization for internal use
    if current_user_id is None:
        return user

    current_user = get_user_or_404(current_user_id)

    # Allow self-access
    if str(user_id) == str(current_user_id):
        return user

    # Allow gestor access within same prefeitura
    if current_user.role == UserRole.GESTOR and user.prefeitura_id == current_user.prefeitura_id:
        return user

    # Log unauthorized access attempt
    audit_logger.log_security_event(
        event_type="unauthorized_user_access",
        severity="medium",
        user_id=current_user_id,
        details={"target_user_id": user_id},
    )
    raise ForbiddenError("Sem permissão para visualizar este usuário")


def update_user(user_id: str, data: dict[str, Any]) -> User:
    """Update user data (nome, email, password, telefone)."""
    user = get_user_or_404(user_id)

    with transactional():
        if nome := data.get("nome"):
            user.nome = nome.strip()

        if email := data.get("email"):
            email_validated = validate_email(email)
            if existing := db.session.query(User).filter_by(email=email_validated).first():
                if existing.id != user.id:
                    raise ConflictError("Email já está em uso")
            user.email = email_validated

        if password := data.get("password"):
            password = validate_password(password)
            user.senha_hash = generate_password_hash(password)

        if telefone := data.get("telefone"):
            user.telefone = telefone.strip()

    return user


def create_aluno_account(gestor_id: str, data: dict[str, Any]) -> Aluno:
    """Create a new aluno account (gestor only)."""
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem cadastrar alunos")

    email = validate_email(data.get("email", ""))
    cpf_clean = validate_cpf(data.get("cpf", ""))

    if db.session.query(User).filter((User.email == email) | (User.cpf == cpf_clean)).first():
        raise ConflictError("Email ou CPF já cadastrado")

    password = validate_password(data.get("password", ""))
    with transactional():
        new_aluno = Aluno(
            prefeitura_id=gestor.prefeitura_id,
            nome=data["nome"],
            email=email,
            senha_hash=generate_password_hash(password),
            cpf=cpf_clean,
            telefone=(data.get("telefone") or "").strip() or None,
            role=UserRole.ALUNO,
            status=UserStatus.PENDING_SIGNUP,
        )

        db.session.add(new_aluno)

    return new_aluno


def create_motorista(gestor_id: str, data: dict[str, Any]) -> Motorista:
    """Create a new driver (gestor only)."""
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem cadastrar motoristas")

    email = validate_email(data.get("email", ""))
    cpf_clean = validate_cpf(data.get("cpf", ""))

    if db.session.query(User).filter((User.email == email) | (User.cpf == cpf_clean)).first():
        raise ConflictError("Email ou CPF já cadastrado")

    if not (cnh := data.get("cnh", "").strip()):
        raise ValidationError("CNH é obrigatória para motoristas")

    if db.session.query(Motorista).filter_by(cnh=cnh).first():
        raise ConflictError("CNH já cadastrada")

    password = validate_password(data.get("password", ""))

    with transactional():
        new_motorista = Motorista(
            prefeitura_id=gestor.prefeitura_id,
            nome=data["nome"],
            email=email,
            senha_hash=generate_password_hash(password),
            cpf=cpf_clean,
            telefone=(data.get("telefone") or "").strip() or None,
            role=UserRole.MOTORISTA,
            cnh=cnh,
        )

        db.session.add(new_motorista)

    return new_motorista


def change_password(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Troca a senha de quem está logado. As regras de segurança ficam em `auth_service.alterar_senha`."""
    current_password = data.get("current_password")
    new_password = data.get("new_password")

    if not current_password or not new_password:
        raise ValidationError("Senha atual e nova senha são obrigatórias")

    return auth_service.alterar_senha(
        user_id,
        senha_atual=current_password,
        nova_senha=new_password,
        confirmacao=data.get("confirm_password", new_password),
    )


def get_motoristas_by_municipio(gestor_id: str):
    gestor = get_gestor_or_403(gestor_id)

    motoristas = User.query.filter(
        User.prefeitura_id == gestor.prefeitura_id, User.role == UserRole.MOTORISTA
    ).all()

    return motoristas


def update_profile(user_id: str, data: dict[str, Any]) -> User:
    """
    Update own profile fields (nome, telefone, receber_notificacoes).
    Motoristas may also update cnh.

    Raises: NotFoundError, ConflictError, ValidationError, AppError
    """
    user = get_user_or_404(user_id)

    with transactional():
        if nome := data.get("nome"):
            user.nome = nome.strip()

        if telefone := data.get("telefone"):
            user.telefone = telefone.strip()

        if "receber_notificacoes" in data:
            user.receber_notificacoes = bool(data["receber_notificacoes"])

        if user.role == UserRole.MOTORISTA and (cnh := data.get("cnh")):
            cnh = cnh.strip()
            existing = db.session.query(Motorista).filter_by(cnh=cnh).first()
            if existing and str(existing.id) != str(user_id):
                raise ConflictError("CNH já cadastrada para outro motorista", field="cnh")
            cast(Motorista, user).cnh = cnh

    audit_logger.log_user_action(
        action="update_profile",
        user_id=user_id,
        resource_type="user",
        resource_id=user_id,
    )
    return user


def delete_motorista(gestor_id: str, motorista_id: str) -> None:
    """
    Remove a motorista account (gestor only, same prefeitura).

    Raises: ForbiddenError, NotFoundError, AppError
    """
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem remover motoristas")

    motorista = db.session.get(User, motorista_id)
    if not motorista or motorista.role != UserRole.MOTORISTA:
        raise NotFoundError("Motorista não encontrado")

    if motorista.prefeitura_id != gestor.prefeitura_id:
        raise ForbiddenError("Proibido remover motoristas de outra prefeitura")

    try:
        with transactional():
            db.session.delete(motorista)
    except ConflictError as e:
        # Só o IntegrityError vira esta mensagem. Antes qualquer exceção saía
        # rotulada como viagem vinculada, o mesmo defeito do `:127`.
        raise AppError(
            "Não é possível remover este motorista pois ele possui viagens vinculadas", 400
        ) from e

    audit_logger.log_user_action(
        action="delete_motorista",
        user_id=gestor_id,
        resource_type="motorista",
        resource_id=motorista_id,
    )


def update_fcm_token(user_id: str, data: dict[str, Any]) -> None:
    """Update the FCM token for a user."""
    user = get_user_or_404(user_id)
    with transactional():
        user.fcm_token = data.get("fcm_token")
