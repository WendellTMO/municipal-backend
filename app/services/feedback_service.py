"""Feedback (relatos dos beta-testers) service."""

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
        )
        db.session.add(feedback)
        db.session.flush()

    return feedback
