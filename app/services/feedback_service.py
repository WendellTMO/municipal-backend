"""Feedback (relatos dos beta-testers) service."""

import base64
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import TipoFeedback
from app.models.feedback import Feedback
from app.models.user import User


def create_feedback(user_id: str, payload: dict[str, Any], user_agent: str | None) -> Feedback:
    """Grava o relato. Usuário e prefeitura vêm do token, nunca do corpo."""
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado.")

    with transactional():
        feedback = Feedback(
            usuario_id=user.id,
            prefeitura_id=user.prefeitura_id,
            tipo=TipoFeedback[payload["tipo"]],
            mensagem=payload["mensagem"],
            tela=payload.get("tela"),
            versao_app=payload.get("versao_app"),
            plataforma=payload.get("plataforma"),
            user_agent=user_agent,
            dispositivo=payload.get("dispositivo"),
            versao_so=payload.get("versao_so"),
            tamanho_tela=payload.get("tamanho_tela"),
            captura=_decodificar_captura(payload.get("captura")),
        )
        db.session.add(feedback)
        db.session.flush()

    return feedback


def _decodificar_captura(captura: str | None) -> bytes | None:
    """O schema já conferiu que é base64 de um JPEG de até 400 KB."""
    if not captura:
        return None
    return base64.b64decode(captura)
