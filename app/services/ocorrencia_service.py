"""Ocorrência (issue reporting) service."""

import logging
from typing import Any

from app.core.authz import get_gestor_or_403
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import StatusOcorrencia, TipoOcorrencia, UserRole
from app.models.ocorrencia import Ocorrencia
from app.models.user import Gestor, User
from app.models.viagem import Viagem
from app.services.notificacao_service import NotificacaoService
from app.utils import audit_logger

logger = logging.getLogger(__name__)


def _ocorrencia_da_prefeitura(ocorrencia: Ocorrencia, prefeitura_id: Any) -> bool:
    """É da prefeitura quando o autor é dela (como no listar) ou a viagem é de uma rota dela."""
    if ocorrencia.autor.prefeitura_id == prefeitura_id:
        return True
    viagem = ocorrencia.viagem
    return (
        viagem is not None
        and viagem.horario_rota is not None
        and viagem.horario_rota.rota.prefeitura_id == prefeitura_id
    )


class OcorrenciaService:
    @staticmethod
    def criar(user_id: str, dados: dict[str, Any]) -> Ocorrencia:
        """
        Aluno ou Motorista reporta um problema.
        Automatically notifies the gestor of the prefeitura.
        """
        user = db.session.get(User, user_id)
        if not user or user.role not in (UserRole.ALUNO, UserRole.MOTORISTA):
            raise ForbiddenError("Apenas alunos e motoristas podem reportar ocorrências.")

        tipo_str = dados.get("tipo")
        try:
            tipo = TipoOcorrencia[tipo_str] if tipo_str else None
        except KeyError:
            tipo = None
        if not tipo:
            raise ValidationError(
                f"Tipo inválido. Valores válidos: {[t.value for t in TipoOcorrencia]}"
            )

        viagem_id = dados.get("viagem_id")
        if viagem_id:
            viagem = db.session.get(Viagem, viagem_id)
            if not viagem:
                raise NotFoundError("Viagem não encontrada.")

        with transactional():
            ocorrencia = Ocorrencia(
                autor_id=user_id,
                viagem_id=viagem_id,
                tipo=tipo,
                descricao=dados.get("descricao"),
                status=StatusOcorrencia.ABERTA,
            )
            db.session.add(ocorrencia)
            db.session.flush()

            # Notify the gestor of this prefeitura
            OcorrenciaService._notificar_gestores(user, ocorrencia)

        audit_logger.log_user_action(
            action="criar_ocorrencia",
            user_id=user_id,
            resource_type="ocorrencia",
            resource_id=str(ocorrencia.id),
        )
        return ocorrencia

    @staticmethod
    def _notificar_gestores(autor: User, ocorrencia: Ocorrencia) -> None:
        tipo_label = {
            TipoOcorrencia.ATRASO: "Atraso",
            TipoOcorrencia.SUPERLOTACAO: "Superlotação",
            TipoOcorrencia.COMPORTAMENTO: "Comportamento",
            TipoOcorrencia.CANCELAMENTO: "Cancelamento",
            TipoOcorrencia.OUTRO: "Outro",
        }.get(ocorrencia.tipo, ocorrencia.tipo.value)

        gestores = db.session.query(Gestor).filter_by(prefeitura_id=autor.prefeitura_id).all()
        for gestor in gestores:
            NotificacaoService._criar_notificacao_interna(
                usuario_id=str(gestor.id),
                titulo=f"Nova Ocorrência: {tipo_label}",
                mensagem=(f"{autor.nome} reportou: {ocorrencia.descricao or tipo_label}"),
            )

    @staticmethod
    def listar(gestor_id: str, status: str | None = None) -> list[Ocorrencia]:
        """Gestor lista ocorrências da sua prefeitura."""

        gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem listar ocorrências.")

        q = (
            db.session.query(Ocorrencia)
            .join(User, Ocorrencia.autor_id == User.id)
            .filter(User.prefeitura_id == gestor.prefeitura_id)
            .order_by(Ocorrencia.created_at.desc())
        )
        if status:
            try:
                status_enum = StatusOcorrencia[status]
            except KeyError:
                raise ValidationError(
                    f"Status inválido. Valores válidos: {[s.value for s in StatusOcorrencia]}"
                ) from None
            q = q.filter(Ocorrencia.status == status_enum)
        return q.all()

    @staticmethod
    def resolver(gestor_id: str, ocorrencia_id: str) -> Ocorrencia:
        """Gestor marca uma ocorrência como resolvida."""

        gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem resolver ocorrências.")

        ocorrencia = db.session.get(Ocorrencia, ocorrencia_id)
        if not ocorrencia or not _ocorrencia_da_prefeitura(ocorrencia, gestor.prefeitura_id):
            raise NotFoundError("Ocorrência não encontrada.")
        if ocorrencia.status == StatusOcorrencia.RESOLVIDA:
            raise ValidationError("Ocorrência já foi resolvida.")

        with transactional():
            ocorrencia.status = StatusOcorrencia.RESOLVIDA

        return ocorrencia
