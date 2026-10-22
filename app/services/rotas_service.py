"""Routes (Rota) service - route management, subscriptions, schedules."""

import logging
from typing import Any

from sqlalchemy.orm import joinedload

from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import DiaDaSemana, SentidoViagem, UserRole
from app.models.geo import Ponto
from app.models.rota import DiasOperacao, HorarioRota, Rota, RotaAluno, RotaPonto
from app.models.user import User
from app.services.viagens_service import gerar_viagens_periodo
from app.utils import audit_logger, validate_uuid

logger = logging.getLogger(__name__)


def list_all_rotas(user_id: str) -> list[Rota]:
    """
    List all routes for user's prefeitura.

    Args:
        user_id: ID of the user requesting the list

    Returns:
        List of Rota objects

    Raises:
        NotFoundError: If user not found
    """
    validate_uuid(user_id, "User ID")
    user = User.query.get(user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    logger.debug(f"User {user_id} listing routes for prefeitura {user.prefeitura_id}")
    return Rota.query.filter_by(prefeitura_id=user.prefeitura_id).all()


def _get_rota_do_tenant(user_id: str, rota_id: str) -> Rota:
    """Resolve a rota garantindo que ela é da prefeitura de quem pediu.

    Guarda única das três leituras de rota. Antes, `get_by_id` e `get_horarios`
    só comparavam a prefeitura para GESTOR e MOTORISTA, deixando ALUNO passar,
    e `get_pontos_by_rota` não comparava nada.

    Raises: NotFoundError, ForbiddenError
    """
    user = User.query.get(user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    rota = Rota.query.get(rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    if rota.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    return rota


def list_my_rotas(user_id: str) -> list[Rota]:
    """List routes linked to the logged-in user."""
    # Mesma validação que a vizinha `list_all_rotas` já fazia. Sem ela o id
    # cru ia para o Postgres e um UUID malformado virava 500 em vez de 400.
    validate_uuid(user_id, "User ID")
    user = User.query.get(user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    match user.role:
        case UserRole.ALUNO:
            inscricoes = RotaAluno.query.filter_by(aluno_id=user.id).all()
            rota_ids = [i.rota_id for i in inscricoes]
            return Rota.query.filter(Rota.id.in_(rota_ids)).all()
        case UserRole.MOTORISTA:
            return Rota.query.filter_by(motorista_padrao_id=user.id).all()
        case UserRole.GESTOR:
            return Rota.query.filter_by(prefeitura_id=user.prefeitura_id).all()
        case _:
            return []


def gerenciar_inscricao_aluno(user_id: str, rota_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """
    Manage student subscription to a route.

    Args:
        user_id: ID of the student
        rota_id: ID of the route
        data: Dictionary with 'acao' field ('inscrever' or 'desinscrever')

    Returns:
        Success message dictionary

    Raises:
        ForbiddenError: If user is not a student or route is from different prefeitura
        NotFoundError: If user or route not found
        ValidationError: If action is invalid
    """
    validate_uuid(user_id, "User ID")
    validate_uuid(rota_id, "Rota ID")

    aluno = db.session.get(User, user_id)
    if not aluno or str(getattr(aluno, "role", "")) != "ALUNO":
        logger.warning(f"Non-student {user_id} attempted route subscription")
        raise ForbiddenError("Apenas alunos podem se inscrever")

    rota = db.session.get(Rota, rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    # Validate tenant isolation - student can only subscribe to routes in their prefeitura
    if rota.prefeitura_id != aluno.prefeitura_id:
        audit_logger.log_security_event(
            event_type="cross_tenant_subscription_attempt",
            severity="high",
            user_id=user_id,
            details={"rota_id": rota_id, "rota_prefeitura": rota.prefeitura_id},
        )
        raise ForbiddenError("Acesso negado a esta rota")

    acao = data.get("acao")
    if not acao or acao not in ["inscrever", "desinscrever"]:
        raise ValidationError("Ação inválida. Use 'inscrever' ou 'desinscrever'.")

    inscricao_existente = RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=aluno.id).first()

    if acao == "inscrever":
        if inscricao_existente:
            return {"message": "Aluno já inscrito nesta rota"}

        with transactional():
            nova_inscricao = RotaAluno(rota_id=rota.id, aluno_id=aluno.id)
            db.session.add(nova_inscricao)

        audit_logger.log_user_action(
            action="subscribe_route",
            user_id=user_id,
            resource_type="rota",
            resource_id=rota_id,
        )
        logger.info(f"Student {user_id} subscribed to route {rota_id}")
        return {"message": "Inscrição realizada com sucesso"}

    if not inscricao_existente:
        raise NotFoundError("Aluno não está inscrito nesta rota")

    with transactional():
        db.session.delete(inscricao_existente)

    audit_logger.log_user_action(
        action="unsubscribe_route",
        user_id=user_id,
        resource_type="rota",
        resource_id=rota_id,
    )
    logger.info(f"Student {user_id} unsubscribed from route {rota_id}")
    return {"message": "Inscrição removida com sucesso"}


def create_rota(gestor_id: str, data: dict[str, Any]) -> Rota:
    """
    Create a new route with optional points and schedules.

    Raises: ForbiddenError, ValidationError, AppError
    """
    user = db.session.get(User, gestor_id)
    if not user or user.role not in (UserRole.GESTOR, UserRole.MOTORISTA):
        raise ForbiddenError("Permissão negada")

    nome = data.get("nome")
    if not nome:
        raise ValidationError("Nome da rota é obrigatório")

    with transactional():
        # If a driver creates a route, automatically assign themselves as the default driver
        motorista_id = data.get("motorista_padrao_id")
        if not motorista_id and user.role == UserRole.MOTORISTA:
            motorista_id = user.id

        rota = Rota(
            nome=nome,
            motorista_padrao_id=motorista_id,
            veiculo_padrao_id=data.get("veiculo_padrao_id"),
            prefeitura_id=user.prefeitura_id,
        )

        db.session.add(rota)
        db.session.flush()

        if "pontos" in data:
            for p_data in data["pontos"]:
                ponto_id = p_data.get("ponto_id")
                ordem = p_data.get("ordem", 0)

                if ponto_id:
                    # Link an existing ponto by ID
                    # Recusa igual à do `add_ponto`. Antes esta função pulava
                    # em silêncio e respondia sucesso, então a rota nascia sem
                    # o ponto e o usuário só descobria na próxima carga. As
                    # duas escritas de ponto do módulo agora falham do mesmo
                    # jeito, com a mesma mensagem.
                    existing_ponto = Ponto.query.get(ponto_id)
                    if not existing_ponto:
                        raise NotFoundError(f"Ponto {ponto_id} não encontrado")
                    if existing_ponto.prefeitura_id != rota.prefeitura_id:
                        raise ForbiddenError(f"O ponto {ponto_id} pertence a outra prefeitura")
                    rota_ponto = RotaPonto(rota_id=rota.id, ponto_id=ponto_id, ordem=ordem)
                    db.session.add(rota_ponto)
                elif "latitude" in p_data and "longitude" in p_data:
                    # Create a brand-new ponto from coordinates
                    novo_ponto = Ponto(
                        prefeitura_id=user.prefeitura_id,
                        latitude=p_data["latitude"],
                        longitude=p_data["longitude"],
                        apelido=p_data.get("apelido", f"Ponto {ordem}"),
                    )
                    db.session.add(novo_ponto)
                    db.session.flush()

                    rota_ponto = RotaPonto(rota_id=rota.id, ponto_id=novo_ponto.id, ordem=ordem)
                    db.session.add(rota_ponto)

        if "horarios" in data:
            for h_data in data["horarios"]:
                novo_horario = HorarioRota(
                    rota_id=rota.id,
                    horario_saida=h_data["horario_saida"],
                    sentido=h_data["sentido"],
                )
                db.session.add(novo_horario)
                db.session.flush()

                dias_list = h_data.get("dias", [])
                for dia_str in dias_list:
                    if dia_str in ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]:
                        novo_dia = DiasOperacao(horario_rota_id=novo_horario.id, dia=dia_str)
                        db.session.add(novo_dia)

    gerar_viagens_periodo(gestor_id=gestor_id, dias_futuros=14)

    return rota


def add_ponto(gestor_id: str, rota_id: str, data: dict[str, Any]) -> None:
    """
    Add points to a route.

    Raises: ForbiddenError, NotFoundError, ValidationError, AppError
    """
    user = User.query.get(gestor_id)

    if not user or user.role not in (UserRole.GESTOR, UserRole.MOTORISTA):
        raise ForbiddenError("Permissão negada")

    rota = Rota.query.get(rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    if rota.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    pontos = data.get("pontos", [])
    if not pontos or not isinstance(pontos, list):
        raise ValidationError("A rota deve conter pelo menos um ponto válido")

    with transactional():
        # Clear existing route points (replacing with new set)
        RotaPonto.query.filter_by(rota_id=rota.id).delete()
        db.session.flush()

        for p in pontos:
            ponto_id = p.get("ponto_id")
            ordem = p.get("ordem", 1)

            # Case 1: Link existing point by ID
            if ponto_id:
                existing_ponto = Ponto.query.get(ponto_id)
                if not existing_ponto:
                    raise NotFoundError(f"Ponto {ponto_id} não encontrado")
                if existing_ponto.prefeitura_id != rota.prefeitura_id:
                    raise ForbiddenError(f"O ponto {ponto_id} pertence a outra prefeitura")

                novo_rota_ponto = RotaPonto(rota_id=rota.id, ponto_id=ponto_id, ordem=ordem)
                db.session.add(novo_rota_ponto)

            # Case 2: Create new point with coordinates
            else:
                nome_p = p.get("nome")
                lat = p.get("latitude")
                lon = p.get("longitude")

                if not nome_p or lat is None or lon is None:
                    raise ValidationError("Ponto novo exige nome, latitude e longitude")

                ponto = Ponto(
                    prefeitura_id=rota.prefeitura_id,
                    apelido=nome_p,
                    latitude=lat,
                    longitude=lon,
                )
                db.session.add(ponto)
                db.session.flush()

                novo_rota_ponto = RotaPonto(rota_id=rota.id, ponto_id=ponto.id, ordem=ordem)
                db.session.add(novo_rota_ponto)


def add_horario(gestor_id: str, rota_id: str, data: dict[str, Any]) -> HorarioRota:
    """
    Add a schedule to a route.

    Raises: ForbiddenError, NotFoundError, ValidationError, AppError
    """
    user = User.query.get(gestor_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Apenas gestores gerenciam horários")

    rota = Rota.query.get(rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    if rota.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    dias_list = data.get("dias", [])
    if not dias_list:
        raise ValidationError("Selecione pelo menos um dia da semana")

    with transactional():
        novo_horario = HorarioRota(
            rota_id=rota.id,
            horario_saida=data.get("horario_saida"),
            sentido=SentidoViagem(data.get("sentido")),
        )
        db.session.add(novo_horario)
        db.session.flush()

        for dia_str in dias_list:
            novo_dia = DiasOperacao(horario_rota_id=novo_horario.id, dia=DiaDaSemana(dia_str))
            db.session.add(novo_dia)

    return novo_horario


def get_horarios(user_id: str, rota_id: str) -> list:
    """
    Get schedules for a route.

    Raises: NotFoundError, ForbiddenError
    """
    rota = _get_rota_do_tenant(user_id, rota_id)

    return rota.grade_horarios


def get_by_id(user_id: str, rota_id: str) -> Rota:
    """
    Get route by ID.

    Raises: NotFoundError, ForbiddenError
    """
    rota = _get_rota_do_tenant(user_id, rota_id)

    return rota


def update_rota(user_id: str, rota_id: str, data: dict[str, Any]) -> Rota:
    """
    Update route name, driver, or vehicle.

    Args:
        user_id: ID of the gestor updating the route
        rota_id: ID of the route to update
        data: Dictionary with fields to update

    Returns:
        Updated Rota object

    Raises:
        ForbiddenError: If user is not a gestor or resource ownership violation
        NotFoundError: If user or route not found
        AppError: If database operation fails
    """
    validate_uuid(user_id, "User ID")
    validate_uuid(rota_id, "Rota ID")

    user = User.query.get(user_id)
    if not user or user.role != UserRole.GESTOR:
        logger.warning(f"Non-gestor {user_id} attempted to update route {rota_id}")
        raise ForbiddenError("Permissão negada")

    rota = Rota.query.get(rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    # Resource ownership validation
    if rota.prefeitura_id != user.prefeitura_id:
        audit_logger.log_security_event(
            event_type="unauthorized_route_update",
            severity="high",
            user_id=user_id,
            details={
                "rota_id": rota_id,
                "user_prefeitura": user.prefeitura_id,
                "rota_prefeitura": rota.prefeitura_id,
            },
        )
        logger.warning(
            f"Cross-tenant route update attempt: user {user_id} tried to update "
            f"route {rota_id} from different prefeitura"
        )
        raise ForbiddenError("Acesso negado")

    updated_fields: list[str] = []

    with transactional():
        if "nome" in data:
            rota.nome = data.get("nome")
            updated_fields.append("nome")

        if "motorista_padrao_id" in data:
            rota.motorista_padrao_id = data.get("motorista_padrao_id")
            updated_fields.append("motorista_padrao_id")

        if "veiculo_padrao_id" in data:
            rota.veiculo_padrao_id = data.get("veiculo_padrao_id")
            updated_fields.append("veiculo_padrao_id")

    audit_logger.log_user_action(
        action="update",
        user_id=user_id,
        resource_type="rota",
        resource_id=rota_id,
        details={"updated_fields": updated_fields},
    )
    logger.info(f"Route {rota_id} updated by {user_id}: {', '.join(updated_fields)}")

    return rota


def delete_rota(user_id: str, rota_id: str) -> None:
    """
    Delete a route.

    Args:
        user_id: ID of the gestor deleting the route
        rota_id: ID of the route to delete

    Raises:
        ForbiddenError: If user is not a gestor or resource ownership violation
        NotFoundError: If user or route not found
        AppError: If database operation fails
    """
    validate_uuid(user_id, "User ID")
    validate_uuid(rota_id, "Rota ID")

    user = User.query.get(user_id)
    if not user or user.role != UserRole.GESTOR:
        logger.warning(f"Non-gestor {user_id} attempted to delete route {rota_id}")
        raise ForbiddenError("Permissão negada")

    rota = Rota.query.get(rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    # Resource ownership validation
    if rota.prefeitura_id != user.prefeitura_id:
        audit_logger.log_security_event(
            event_type="unauthorized_route_deletion",
            severity="critical",
            user_id=user_id,
            details={
                "rota_id": rota_id,
                "user_prefeitura": user.prefeitura_id,
                "rota_prefeitura": rota.prefeitura_id,
            },
        )
        logger.error(
            f"Critical: Cross-tenant route deletion attempt by user {user_id} on route {rota_id}"
        )
        raise ForbiddenError("Acesso negado")

    with transactional():
        # Store route name for audit log
        rota_nome = rota.nome

        db.session.delete(rota)

    audit_logger.log_user_action(
        action="delete",
        user_id=user_id,
        resource_type="rota",
        resource_id=rota_id,
        details={"rota_nome": rota_nome},
    )
    logger.info(f"Route {rota_id} ({rota_nome}) deleted by gestor {user_id}")


def get_pontos_by_rota(user_id: str, rota_id: str) -> list[dict[str, Any]]:
    _get_rota_do_tenant(user_id, rota_id)

    # joinedload traz ponto e instituição na mesma query (evita N+1)
    rota_pontos = (
        RotaPonto.query.filter_by(rota_id=rota_id)
        .options(joinedload(RotaPonto.ponto).joinedload(Ponto.instituicao))
        .order_by(RotaPonto.ordem.asc())
        .all()
    )

    resultado = []
    for rp in rota_pontos:
        ponto = rp.ponto
        instituicao = None
        if ponto.instituicao:
            instituicao = {
                "id": str(ponto.instituicao.id),
                "nome": ponto.instituicao.nome,
                "tipo": ponto.instituicao.tipo.value,
            }
        resultado.append(
            {
                "id": str(ponto.id),
                "apelido": ponto.apelido,
                "latitude": float(ponto.latitude),
                "longitude": float(ponto.longitude),
                "ordem": rp.ordem,
                "instituicao": instituicao,
            }
        )

    return resultado
