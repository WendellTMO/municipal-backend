"""Authorization primitives shared across services.

Lives in ``app.core`` (not ``app.services``) so that any service can depend on
it without creating import cycles between service modules.
"""

import logging
from typing import cast

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.base import db
from app.models.enum import UserRole
from app.models.onibus import Onibus
from app.models.user import Gestor, Motorista, User
from app.utils import validate_uuid

logger = logging.getLogger(__name__)


def get_user_or_404(user_id: str) -> User:
    """Get user by ID or raise NotFoundError."""
    validate_uuid(user_id, "User ID")
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")
    return user


def get_gestor_or_403(
    user_id: str, message: str = "Apenas gestores podem executar esta ação"
) -> Gestor:
    """Resolve ``user_id`` and assert it is a gestor, else raise ForbiddenError."""
    user = get_user_or_404(user_id)
    if user.role != UserRole.GESTOR:
        raise ForbiddenError(message)
    return cast(Gestor, user)


def exigir_motorista_e_onibus_da_prefeitura(
    prefeitura_id: object, motorista_id: object, onibus_id: object
) -> None:
    """Motorista e ônibus informados pelo cliente precisam ser da prefeitura de quem pede."""
    if motorista_id:
        validate_uuid(str(motorista_id), "Motorista ID")
        motorista = db.session.get(Motorista, motorista_id)
        if motorista is None or motorista.prefeitura_id != prefeitura_id:
            raise NotFoundError("Motorista não encontrado")
    if onibus_id:
        validate_uuid(str(onibus_id), "Ônibus ID")
        onibus = db.session.get(Onibus, onibus_id)
        if onibus is None or onibus.prefeitura_id != prefeitura_id:
            raise NotFoundError("Ônibus não encontrado")
