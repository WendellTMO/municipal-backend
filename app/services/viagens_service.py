"""Trips (Viagem) service - trip management, student confirmations."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.transaction import transactional
from app.extensions import scheduler
from app.models.base import db
from app.models.enum import DiaDaSemana, SentidoViagem, StatusViagem, UserRole
from app.models.geo import Ponto
from app.models.rota import DiasOperacao, HorarioRota, Rota, RotaAluno, RotaPonto
from app.models.user import Aluno, User
from app.models.viagem import AlunosConfirmados, TelemetriaViagem, Viagem, ViagemPonto
from app.services.notificacao_service import NotificacaoService
from app.tasks.viagem_tasks import realizar_auto_checkin
from app.utils import audit_logger
from app.utils.geo_utils import calcular_distancia_metros

logger = logging.getLogger(__name__)


# As listagens de viagem são serializadas por acessores `fields.Method` do
# `ViagemListResponseSchema`, que percorrem estas três relações por viagem. Sem
# carga antecipada cada viagem da página dispara os seus próprios SELECTs, e o
# custo cresce linearmente com o tamanho da página.
#
# `selectinload` nas coleções (uma query a mais por relação, não por linha) e
# `joinedload` no caminho many-to-one até a rota.
#
# É função, e não constante de módulo, de propósito: avaliar as opções no
# import forçaria a configuração dos mappers antes de todos os modelos estarem
# registrados, e o SQLAlchemy falha ao resolver `Prefeitura`.
def _carga_da_listagem():
    return (
        joinedload(Viagem.horario_rota)
        .joinedload(HorarioRota.rota)
        .selectinload(Rota.alunos_inscritos),
        selectinload(Viagem.alunos_confirmados)
        .joinedload(AlunosConfirmados.aluno)
        .joinedload(Aluno.instituicao),
        selectinload(Viagem.pontos_visitados),
    )


def _get_dia_semana_enum(data_obj: date) -> DiaDaSemana:
    """Convert weekday (0=Monday) to DiaDaSemana enum."""
    dias_map = {
        0: DiaDaSemana.SEG,
        1: DiaDaSemana.TER,
        2: DiaDaSemana.QUA,
        3: DiaDaSemana.QUI,
        4: DiaDaSemana.SEX,
        5: DiaDaSemana.SAB,
        6: DiaDaSemana.DOM,
    }
    dia = dias_map.get(data_obj.weekday())
    if not dia:
        raise ValidationError("Data inválida para cálculo do dia da semana")
    return dia


def _popular_dados_da_viagem(viagem_obj: Viagem, rota_obj: Rota) -> None:
    """Helper function that copies students and stops from route to trip."""
    inscricoes = db.session.query(RotaAluno).filter_by(rota_id=rota_obj.id).all()

    # Batch load all alunos to avoid N+1 queries
    aluno_ids = [i.aluno_id for i in inscricoes]
    if aluno_ids:
        alunos = db.session.query(Aluno).filter(Aluno.usuario_id.in_(aluno_ids)).all()
        alunos_map = {a.usuario_id: a for a in alunos}
    else:
        alunos_map = {}

    for inscricao in inscricoes:
        aluno = alunos_map.get(inscricao.aluno_id)
        if not aluno:
            continue

        conf = AlunosConfirmados(
            viagem_id=viagem_obj.id,
            aluno_id=aluno.usuario_id,
            confirmacao=False,
            ponto_embarque_id=None,
            ponto_destino_id=None,
        )
        db.session.add(conf)

    pontos_rota = (
        db.session.query(RotaPonto).filter_by(rota_id=rota_obj.id).order_by(RotaPonto.ordem).all()
    )

    ordem_real = 1
    for pr in pontos_rota:
        vp = ViagemPonto(
            viagem_id=viagem_obj.id, ponto_id=pr.ponto_id, ordem=ordem_real, visitado=False
        )
        db.session.add(vp)
        ordem_real += 1


def get_proximas_viagens_aluno(user_id: str) -> list[Viagem]:
    """Returns upcoming scheduled trips for the logged student."""
    aluno = db.session.get(User, user_id)
    if not aluno or aluno.role != UserRole.ALUNO:
        raise ForbiddenError("Apenas alunos podem ver sua agenda de viagens")

    # Data local, não UTC. O `docker-compose.prod.yml` define
    # `TZ: America/Sao_Paulo`, então "hoje" para o aluno é a data brasileira. O
    # `gerar_viagens_periodo` e o `Aluno.is_minor` já usam `date.today()`; esta
    # função era a única com referência diferente. Com UTC, entre 21h e
    # meia-noite a data virava antes e a viagem de hoje sumia da agenda.
    hoje = date.today()

    query = (
        db.session.query(Viagem)
        .join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
        .join(Rota, HorarioRota.rota_id == Rota.id)
        .join(RotaAluno, Rota.id == RotaAluno.rota_id)
        .outerjoin(
            AlunosConfirmados,
            (AlunosConfirmados.viagem_id == Viagem.id) & (AlunosConfirmados.aluno_id == aluno.id),
        )
        # NOTE: this outerjoin does not filter Viagem.alunos_confirmados -- the
        # relationship still loads every student confirmed on the trip.
        # ViagemAgendaAlunoResponseSchema selects the caller's own record by
        # aluno_id when serializing.
        .filter(
            RotaAluno.aluno_id == aluno.id,
            Viagem.status.in_([StatusViagem.AGENDADA, StatusViagem.EM_ANDAMENTO]),
            Viagem.data >= hoje,
        )
        .order_by(Viagem.data.asc(), HorarioRota.horario_saida.asc())
    )

    viagens = query.all()

    # Sugestão de pontos por viagem: a instituição fica de um lado, o padrão lembrado do outro.
    ponto_instituicao = _ponto_da_instituicao(aluno)
    inscricoes: dict[Any, RotaAluno] = {}
    for inscricao in RotaAluno.query.filter_by(aluno_id=aluno.id).all():
        inscricoes[inscricao.rota_id] = inscricao
    for viagem in viagens:
        inscricao = inscricoes[viagem.horario_rota.rota_id]
        sentido = viagem.horario_rota.sentido
        padrao_embarque = inscricao.ponto_embarque_padrao_id
        padrao_desembarque = inscricao.ponto_desembarque_padrao_id
        if sentido == SentidoViagem.VOLTA:
            viagem.ponto_embarque_sugerido_id = ponto_instituicao
            viagem.ponto_destino_sugerido_id = padrao_desembarque
            viagem.precisa_escolher_ponto = padrao_desembarque is None
        elif sentido == SentidoViagem.CIRCULAR:
            viagem.ponto_embarque_sugerido_id = padrao_embarque
            viagem.ponto_destino_sugerido_id = padrao_desembarque
            viagem.precisa_escolher_ponto = padrao_embarque is None or padrao_desembarque is None
        else:
            viagem.ponto_embarque_sugerido_id = padrao_embarque
            viagem.ponto_destino_sugerido_id = ponto_instituicao
            viagem.precisa_escolher_ponto = padrao_embarque is None

    return viagens


def _ponto_da_instituicao(aluno: Aluno) -> Any:
    if aluno.instituicao is None:
        return None
    return aluno.instituicao.ponto_id


def _ponto_da_rota(rota_id: Any, ponto_id: Any, campo: str) -> Any:
    """Ponto escolhido pelo aluno: precisa existir e pertencer à rota da viagem."""
    if ponto_id is None:
        raise ValidationError(
            "Escolha o ponto na rota ou defina o seu ponto padrão",
            details={"field": campo},
        )
    na_rota = RotaPonto.query.filter_by(rota_id=rota_id, ponto_id=ponto_id).first()
    if na_rota is None:
        raise ValidationError("O ponto não pertence à rota da viagem", details={"field": campo})
    return ponto_id


def _resolver_pontos(
    aluno: Aluno, horario: HorarioRota, inscricao: RotaAluno, data: dict[str, Any]
) -> tuple[Any, Any, dict[str, Any]]:
    """Devolve (embarque, destino, escolhas a lembrar) conforme o sentido da viagem.

    IDA: o aluno escolhe onde embarca e desce na instituição. VOLTA: parte da instituição
    e o aluno escolhe onde desce. CIRCULAR: o aluno escolhe os dois, na rota.
    """
    ponto_instituicao = _ponto_da_instituicao(aluno)
    escolhas: dict[str, Any] = {}

    embarque = None
    if horario.sentido != SentidoViagem.VOLTA:
        embarque = data.get("ponto_embarque_id")
        if embarque is not None:
            escolhas["ponto_embarque_padrao_id"] = embarque
        else:
            embarque = inscricao.ponto_embarque_padrao_id
        embarque = _ponto_da_rota(horario.rota_id, embarque, "ponto_embarque_id")

    destino = None
    if horario.sentido != SentidoViagem.IDA:
        destino = data.get("ponto_desembarque_id")
        if destino is not None:
            escolhas["ponto_desembarque_padrao_id"] = destino
        else:
            destino = inscricao.ponto_desembarque_padrao_id
        destino = _ponto_da_rota(horario.rota_id, destino, "ponto_desembarque_id")

    if horario.sentido == SentidoViagem.IDA:
        destino = ponto_instituicao
    elif horario.sentido == SentidoViagem.VOLTA:
        embarque = ponto_instituicao
    if ponto_instituicao is None and horario.sentido != SentidoViagem.CIRCULAR:
        raise ValidationError(
            "Seu cadastro não tem instituição com ponto de parada. Fale com o gestor.",
            details={"field": "instituicao_id"},
        )
    return embarque, destino, escolhas


def confirmar_presenca_aluno(
    user_id: str, viagem_id: str, data: dict[str, Any]
) -> AlunosConfirmados:
    """Student confirms or cancels attendance."""
    aluno = db.session.get(Aluno, user_id)
    if not aluno:
        # fallback to role check (polymorphic table)
        aluno_user = db.session.get(User, user_id)
        if aluno_user and aluno_user.role == UserRole.ALUNO:
            aluno = db.session.get(Aluno, user_id)

    if not aluno:
        raise ForbiddenError("Aluno não encontrado")

    confirmacao: bool = data["confirmacao"]

    with transactional():
        viagem = db.session.get(Viagem, viagem_id)
        if not viagem:
            raise NotFoundError("Viagem não encontrada")

        registro = db.session.get(AlunosConfirmados, (viagem.id, aluno.usuario_id))

        if not registro:
            horario = db.session.get(HorarioRota, viagem.horario_rota_id)
            if not horario:
                raise NotFoundError("Horário da viagem não encontrado")

            inscricao = db.session.get(RotaAluno, (horario.rota_id, aluno.usuario_id))
            if not inscricao:
                raise ForbiddenError("Você não está inscrito na rota desta viagem")

            registro = AlunosConfirmados(
                viagem_id=viagem.id,
                aluno_id=aluno.usuario_id,
                confirmacao=False,
                ponto_embarque_id=None,
                ponto_destino_id=None,
            )
            db.session.add(registro)

        if confirmacao:
            horario = db.session.get(HorarioRota, viagem.horario_rota_id)
            if not horario:
                raise NotFoundError("Horário da viagem não encontrado")

            inscricao = db.session.get(RotaAluno, (horario.rota_id, aluno.usuario_id))
            if inscricao is None:
                raise ForbiddenError("Você não está inscrito na rota desta viagem")
            embarque, destino, escolhas = _resolver_pontos(aluno, horario, inscricao, data)

            registro.confirmacao = True
            registro.ponto_embarque_id = embarque
            registro.ponto_destino_id = destino
            if data.get("lembrar_escolha") is True:
                for coluna, ponto_id in escolhas.items():
                    setattr(inscricao, coluna, ponto_id)
        else:
            registro.confirmacao = False
            registro.ponto_embarque_id = None
            registro.ponto_destino_id = None

        return registro


def listar_pontos_embarque(user_id: str, viagem_id: str) -> list[dict]:
    """
    Retorna os pontos de embarque disponíveis para uma viagem específica.

    Raises: ForbiddenError, NotFoundError, AppError
    """
    aluno = db.session.get(User, user_id)
    if not aluno or aluno.role != UserRole.ALUNO:
        raise ForbiddenError("Acesso restrito a alunos")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    horario = db.session.get(HorarioRota, viagem.horario_rota_id)
    if not horario:
        raise AppError("Horário não encontrado", 500)

    inscricao = (
        db.session.query(RotaAluno).filter_by(rota_id=horario.rota_id, aluno_id=aluno.id).first()
    )

    if not inscricao:
        raise ForbiddenError("Você não está inscrito na rota desta viagem")

    pontos_query = (
        db.session.query(RotaPonto, Ponto)
        .join(Ponto, RotaPonto.ponto_id == Ponto.id)
        .filter(RotaPonto.rota_id == horario.rota_id)
        .order_by(RotaPonto.ordem)
        .all()
    )

    resultado = []
    for rp, ponto_obj in pontos_query:
        resultado.append(
            {
                "ponto_id": str(ponto_obj.id),
                "apelido": ponto_obj.apelido,
                "latitude": float(ponto_obj.latitude),
                "longitude": float(ponto_obj.longitude),
                "ordem": rp.ordem,
            }
        )

    return resultado


def gerar_viagem(user_id: str, data_input: dict) -> Viagem:
    """
    Gera UMA viagem para UMA rota específica (Modo Manual).

    Raises: ForbiddenError, NotFoundError, ValidationError, ConflictError, AppError
    """
    user = db.session.get(User, user_id)
    if not user or user.role not in (UserRole.GESTOR, UserRole.MOTORISTA):
        raise ForbiddenError("Permissão negada")

    rota_id = data_input.get("rota_id")
    motorista_id = data_input.get("motorista_id")

    data_viagem = data_input.get("data")
    if not data_viagem:
        raise ValidationError("Data é obrigatória")

    rota = db.session.get(Rota, rota_id)
    if not rota:
        raise NotFoundError("Rota não encontrada")

    if rota.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    dia_semana = _get_dia_semana_enum(data_viagem)

    horario_selecionado = (
        db.session.query(HorarioRota)
        .join(DiasOperacao)
        .filter(HorarioRota.rota_id == rota.id, DiasOperacao.dia == dia_semana)
        .first()
    )
    if not horario_selecionado:
        raise NotFoundError(f"Horário não encontrado para a rota {rota.nome} no dia {dia_semana}")

    existente = (
        db.session.query(Viagem.id)
        .filter_by(data=data_viagem, horario_rota_id=horario_selecionado.id)
        .first()
    )
    if existente:
        raise ConflictError(
            f"Viagem já gerada para este dia/horário: {data_viagem} {horario_selecionado.horario_saida.strftime('%H:%M')}"
        )

    with transactional():
        nova_viagem = Viagem(
            data=data_viagem,
            horario_rota_id=horario_selecionado.id,
            motorista_id=motorista_id,
            veiculo_id=rota.veiculo_padrao_id,
            status=StatusViagem.AGENDADA,
        )
        db.session.add(nova_viagem)
        db.session.flush()  # ensure nova_viagem.id

        _popular_dados_da_viagem(nova_viagem, rota)

        return nova_viagem


def gerar_viagens_em_lote(user_id: str, data_viagem: date) -> dict[str, Any]:
    """Batch create trips for all routes of a prefeitura on a specific date."""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Permissão negada. Apenas gestores podem gerar lote.")

    dia_semana = _get_dia_semana_enum(data_viagem)
    rotas = db.session.query(Rota).filter(Rota.prefeitura_id == user.prefeitura_id).all()

    relatorio: dict[str, Any] = {
        "total_rotas_analisadas": len(rotas),
        "viagens_criadas": 0,
        "detalhes": [],
    }

    with transactional():
        for rota in rotas:
            horarios_validos = (
                db.session.query(HorarioRota)
                .join(DiasOperacao)
                .filter(HorarioRota.rota_id == rota.id, DiasOperacao.dia == dia_semana)
                .all()
            )

            for horario in horarios_validos:
                existe = (
                    db.session.query(Viagem.id)
                    .filter_by(data=data_viagem, horario_rota_id=horario.id)
                    .first()
                )
                if existe:
                    continue

                nova_viagem = Viagem(
                    data=data_viagem,
                    horario_rota_id=horario.id,
                    motorista_id=rota.motorista_padrao_id,
                    veiculo_id=rota.veiculo_padrao_id,
                    status=StatusViagem.AGENDADA,
                )
                db.session.add(nova_viagem)
                db.session.flush()

                _popular_dados_da_viagem(nova_viagem, rota)

                relatorio["viagens_criadas"] += 1
                relatorio["detalhes"].append(
                    f"Viagem criada: {rota.nome} - {horario.horario_saida}"
                )

        return relatorio


def list_viagens_motorista(user_id: str) -> list[Viagem]:
    """List trips assigned to the driver."""
    return (
        db.session.query(Viagem)
        .options(*_carga_da_listagem())
        .filter_by(motorista_id=user_id)
        .order_by(Viagem.data.desc())
        .all()
    )


def controlar_viagem(user_id: str, viagem_id: str, data: dict[str, Any]) -> Viagem:
    """Start or finish a trip. Expects schema-validated payload with 'acao'."""
    user = db.session.get(User, user_id)
    viagem = db.session.get(Viagem, viagem_id)

    if not user:
        raise NotFoundError("Usuário não encontrado")

    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    if user.role == UserRole.MOTORISTA and viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")

    acao = data.get("acao")

    with transactional():
        if acao == "INICIAR":
            if viagem.status != StatusViagem.AGENDADA:
                raise ValidationError(
                    f"Não é possível iniciar viagem com status {viagem.status.name}"
                )
            viagem.status = StatusViagem.EM_ANDAMENTO
            viagem.inicio_real = datetime.now(UTC)

            NotificacaoService.notificar_alunos_viagem_iniciada(viagem_id=viagem_id)

        elif acao == "FINALIZAR":
            if viagem.status != StatusViagem.EM_ANDAMENTO:
                raise ValidationError("A viagem precisa estar em andamento para ser finalizada")
            viagem.status = StatusViagem.FINALIZADA
            viagem.fim_real = datetime.now(UTC)

            rastros = (
                TelemetriaViagem.query.filter_by(viagem_id=viagem.id)
                .order_by(TelemetriaViagem.timestamp.asc())
                .all()
            )

            km_total = 0.0
            if len(rastros) > 1:
                distancia_metros = 0.0
                for i in range(len(rastros) - 1):
                    p1 = rastros[i]
                    p2 = rastros[i + 1]
                    distancia_metros += calcular_distancia_metros(
                        float(p1.latitude),
                        float(p1.longitude),
                        float(p2.latitude),
                        float(p2.longitude),
                    )
                km_total = round(distancia_metros / 1000.0, 2)

            viagem.km_real = km_total
        else:
            raise ValidationError("Ação inválida. Use INICIAR ou FINALIZAR")

        return viagem


def list_viagens_gestor(user_id: str, filters: dict[str, Any]) -> list[Viagem]:
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Apenas gestores podem acessar o histórico completo")

    query = (
        db.session.query(Viagem)
        .join(HorarioRota)
        .join(Rota)
        .filter(Rota.prefeitura_id == user.prefeitura_id)
    )

    if filters.get("data_inicio"):
        query = query.filter(Viagem.data >= filters.get("data_inicio"))

    if filters.get("data_fim"):
        query = query.filter(Viagem.data <= filters.get("data_fim"))

    if filters.get("status"):
        query = query.filter(Viagem.status == filters.get("status"))

    if filters.get("motorista_id"):
        query = query.filter(Viagem.motorista_id == filters.get("motorista_id"))

    if filters.get("rota_id"):
        query = query.filter(Rota.id == filters.get("rota_id"))

    return (
        query.options(*_carga_da_listagem())
        .order_by(Viagem.data.desc(), Viagem.horario_rota_id)
        .all()
    )


def cancelar_viagem(user_id: str, viagem_id: str) -> dict[str, Any]:
    """Cancela uma viagem e notifica alunos confirmados"""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Apenas gestores podem cancelar viagens")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    if viagem.status in (StatusViagem.FINALIZADA, StatusViagem.CANCELADA):
        raise ValidationError(f"Não é possível cancelar uma viagem com status {viagem.status.name}")

    with transactional():
        viagem.status = StatusViagem.CANCELADA

        confirmados = AlunosConfirmados.query.filter_by(viagem_id=viagem.id, confirmacao=True).all()
        data_formatada = viagem.data.strftime("%d/%m/%Y")

        for conf in confirmados:
            NotificacaoService._criar_notificacao_interna(
                usuario_id=conf.aluno_id,
                titulo="Viagem Cancelada",
                mensagem=f"Atenção! A viagem da rota agendada para o dia {data_formatada} foi cancelada pela prefeitura.",
            )

    audit_logger.log_user_action(
        action="cancelar_viagem", user_id=user_id, resource_type="viagem", resource_id=viagem_id
    )

    return {"message": "Viagem cancelada com sucesso", "alunos_notificados": len(confirmados)}


def atualizar_localizacao(user_id: str, viagem_id: str, data: dict) -> dict:
    """Atualiza o GPS do motorista, salva telemetria e engatilha o Auto-Checkin."""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.MOTORISTA:
        raise ForbiddenError("Apenas motoristas podem enviar localização em tempo real")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    if viagem.status != StatusViagem.EM_ANDAMENTO:
        raise ValidationError(f"A viagem não está em andamento (Status: {viagem.status.name})")

    agora = datetime.now(UTC)

    viagem.motorista_lat = data["latitude"]
    viagem.motorista_lon = data["longitude"]
    viagem.motorista_gps_hora = agora

    rastro = TelemetriaViagem(
        viagem_id=viagem.id, latitude=data["latitude"], longitude=data["longitude"], timestamp=agora
    )
    db.session.add(rastro)
    db.session.commit()

    proximos_pontos = (
        ViagemPonto.query.filter_by(viagem_id=viagem.id, visitado=False)
        .order_by(ViagemPonto.ordem)
        .all()
    )

    if not proximos_pontos:
        return {"message": "Todos os pontos já foram visitados. Viagem quase concluída!"}

    proximo_ponto = proximos_pontos[0]
    ponto_geo = proximo_ponto.ponto

    distancia_metros = calcular_distancia_metros(
        float(data["latitude"]),
        float(data["longitude"]),
        float(ponto_geo.latitude),
        float(ponto_geo.longitude),
    )

    DISTANCIA_GATILHO = 1000

    if distancia_metros <= DISTANCIA_GATILHO and not proximo_ponto.aviso_aproximacao_enviado:
        alunos_neste_ponto = AlunosConfirmados.query.filter_by(
            viagem_id=viagem.id, confirmacao=True, ponto_embarque_id=ponto_geo.id, embarcou=False
        ).all()

        data_execucao = agora + timedelta(minutes=5)

        for conf in alunos_neste_ponto:
            NotificacaoService._criar_notificacao_interna(
                usuario_id=conf.aluno_id,
                titulo="🚌 O Ônibus está chegando!",
                mensagem=f"O motorista está a aproximadamente {int(distancia_metros)}m do seu ponto de embarque ({ponto_geo.apelido}). Prepare-se!",
            )

            job_id = f"checkin_{viagem.id}_{conf.aluno_id}"

            if not scheduler.get_job(job_id):

                scheduler.add_job(
                    id=job_id,
                    func=realizar_auto_checkin,
                    args=[str(viagem.id), str(conf.aluno_id), 1],
                    trigger="date",
                    run_date=data_execucao,
                )

        proximo_ponto.aviso_aproximacao_enviado = True
        db.session.commit()
        return {
            "message": "Localização salva. Ponto próximo alcançado, notificações e auto-checkin engatilhados!",
            "distancia_metros": int(distancia_metros),
        }

    return {
        "message": "Localização atualizada silenciosamente com telemetria.",
        "distancia_metros": int(distancia_metros),
    }


def obter_localizacao_onibus(user_id: str, viagem_id: str) -> dict:
    """
    Retorna a localização atual do ônibus (GPS do motorista) para uma viagem em andamento.
    Aluno (confirmado na viagem) ou motorista da viagem podem consultar.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise ForbiddenError("Acesso negado")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    if viagem.status != StatusViagem.EM_ANDAMENTO:
        raise ValidationError(
            "A localização do ônibus só está disponível enquanto a viagem está em andamento."
        )

    if user.role == UserRole.MOTORISTA:
        if viagem.motorista_id != user.id:
            raise ForbiddenError("Apenas o motorista desta viagem pode consultar a localização.")
    elif user.role == UserRole.ALUNO:
        conf = AlunosConfirmados.query.filter_by(viagem_id=viagem.id, aluno_id=user_id).first()
        if not conf or not conf.confirmacao:
            raise ForbiddenError(
                "Você precisa estar confirmado nesta viagem para ver a localização do ônibus."
            )
    else:
        raise ForbiddenError(
            "Apenas alunos confirmados ou o motorista podem consultar a localização do ônibus."
        )

    return {
        "latitude": float(viagem.motorista_lat) if viagem.motorista_lat is not None else None,
        "longitude": float(viagem.motorista_lon) if viagem.motorista_lon is not None else None,
        "atualizado_em": (
            viagem.motorista_gps_hora.isoformat() if viagem.motorista_gps_hora else None
        ),
    }


def atualizar_localizacao_aluno(user_id: str, viagem_id: str, data: dict) -> dict:
    """Updates the student's current GPS coordinates for auto-checkin."""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.ALUNO:
        raise ForbiddenError("Apenas alunos podem enviar a localização de embarque.")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada.")

    if viagem.status != StatusViagem.EM_ANDAMENTO:
        raise ValidationError("A viagem precisa de estar em andamento para rastrear o embarque.")

    conf = AlunosConfirmados.query.filter_by(viagem_id=viagem.id, aluno_id=user_id).first()
    if not conf or not conf.confirmacao:
        raise ForbiddenError("O utilizador não está confirmado nesta viagem.")

    if conf.embarcou:
        return {
            "message": "Embarque já realizado. O rastreio em tempo real pode ser desligado.",
            "embarcou": True,
        }

    agora = datetime.now(UTC)

    conf.aluno_lat = data["latitude"]
    conf.aluno_lon = data["longitude"]
    conf.aluno_gps_hora = agora

    db.session.commit()

    return {
        "message": "Localização do aluno atualizada com sucesso para validação de check-in.",
        "embarcou": False,
    }


def gerar_viagens_periodo(gestor_id: str, dias_futuros: int = 14) -> int:
    """
    Função centralizada para gerar viagens em lote para os próximos N dias.
    Pode ser chamada tanto por Jobs em background quanto por ações de usuário.

    Retorna o total de viagens criadas. Cada dia é isolado: uma falha em um dia
    não impede os seguintes, já que antes um erro no dia 3 abortava os outros
    11 em silêncio e o job ainda registrava sucesso.
    """
    hoje = date.today()
    total = 0

    for i in range(dias_futuros):
        data_alvo = hoje + timedelta(days=i)
        try:
            relatorio = gerar_viagens_em_lote(user_id=gestor_id, data_viagem=data_alvo)
            total += relatorio["viagens_criadas"]
        except Exception as e:
            logger.error(f"Falha ao gerar viagens de {data_alvo} para o gestor {gestor_id}: {e}")

    logger.info(f"Gestor {gestor_id}: {total} viagens criadas em {dias_futuros} dias")
    return total
