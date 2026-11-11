"""Trips (Viagem) service - trip management, student confirmations."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import contains_eager, joinedload, selectinload

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
from app.models.geo import Instituicao, Ponto
from app.models.rota import (
    DiasOperacao,
    HorarioRota,
    PadraoPontosAluno,
    Rota,
    RotaAluno,
    RotaPonto,
)
from app.models.user import Aluno, User
from app.models.viagem import AlunosConfirmados, TelemetriaViagem, Viagem, ViagemPonto
from app.services.notificacao_service import NotificacaoService
from app.tasks.expiracao_tasks import MOTIVO_NAO_REALIZADA
from app.tasks.viagem_tasks import realizar_auto_checkin
from app.utils import audit_logger
from app.utils.geo_utils import calcular_distancia_metros

logger = logging.getLogger(__name__)

# Envio de GPS sob demanda: o motorista só acelera quando alguém consultou há pouco.
JANELA_OBSERVADOR_SEGUNDOS = 45
INTERVALO_COM_OBSERVADOR = 5
INTERVALO_SEM_OBSERVADOR = 30


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


def get_proximas_viagens_aluno(
    user_id: str,
    limit: int | None = None,
    offset: int = 0,
    rota_id: Any = None,
) -> list[Viagem]:
    """Returns upcoming trips (scheduled, running or cancelled) for the logged student.

    `limit`/`offset` paginam a lista (sem `limit` devolve tudo, como o app antigo espera) e
    `rota_id` restringe a uma rota.
    """
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
            # A cancelada fica na agenda com o motivo: o aluno precisa ver que ela não vai acontecer.
            Viagem.status.in_(
                [StatusViagem.AGENDADA, StatusViagem.EM_ANDAMENTO, StatusViagem.CANCELADA]
            ),
            Viagem.data >= hoje,
        )
        # Horário e rota já vêm do join acima; confirmados em uma consulta só (sem uma por viagem).
        .options(
            contains_eager(Viagem.horario_rota).contains_eager(HorarioRota.rota),
            selectinload(Viagem.alunos_confirmados),
        )
        .order_by(Viagem.data.asc(), HorarioRota.horario_saida.asc(), Viagem.id.asc())
    )
    if rota_id is not None:
        query = query.filter(Rota.id == rota_id)
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    viagens = query.all()

    # Total de alunos por rota em uma consulta, em vez de uma contagem por viagem.
    rotas_da_pagina = {viagem.horario_rota.rota_id for viagem in viagens}
    totais_por_rota: dict[Any, int] = {}
    if rotas_da_pagina:
        linhas = (
            db.session.query(RotaAluno.rota_id, func.count())
            .filter(RotaAluno.rota_id.in_(rotas_da_pagina))
            .group_by(RotaAluno.rota_id)
            .all()
        )
        for rota_da_linha, total in linhas:
            totais_por_rota[rota_da_linha] = total

    # Sugestão de pontos por viagem: a instituição fica de um lado, o padrão lembrado do outro.
    ponto_instituicao = _ponto_da_instituicao(aluno)
    inscricoes: dict[Any, RotaAluno] = {}
    for inscricao in RotaAluno.query.filter_by(aluno_id=aluno.id).all():
        inscricoes[inscricao.rota_id] = inscricao
    # Pontos lembrados por horário (uma consulta para a página inteira).
    padroes_por_horario: dict[Any, PadraoPontosAluno] = {}
    horarios_da_pagina = {viagem.horario_rota_id for viagem in viagens}
    if horarios_da_pagina:
        for padrao_salvo in PadraoPontosAluno.query.filter(
            PadraoPontosAluno.aluno_id == aluno.id,
            PadraoPontosAluno.horario_rota_id.in_(horarios_da_pagina),
        ).all():
            padroes_por_horario[padrao_salvo.horario_rota_id] = padrao_salvo

    for viagem in viagens:
        inscricao = inscricoes[viagem.horario_rota.rota_id]
        viagem.total_alunos_rota = totais_por_rota.get(viagem.horario_rota.rota_id, 0)
        sentido = viagem.horario_rota.sentido
        lembrado = padroes_por_horario.get(viagem.horario_rota_id)
        embarque = lembrado.ponto_embarque_id if lembrado else None
        desembarque = lembrado.ponto_desembarque_id if lembrado else None
        # Sem escolha lembrada: a instituição principal numa ponta (desembarque na ida, embarque
        # na volta) e o padrão antigo da rota na outra.
        if embarque is None:
            if sentido == SentidoViagem.VOLTA:
                embarque = ponto_instituicao
            else:
                embarque = inscricao.ponto_embarque_padrao_id
        if desembarque is None:
            if sentido == SentidoViagem.IDA:
                desembarque = ponto_instituicao
            else:
                desembarque = inscricao.ponto_desembarque_padrao_id
        viagem.ponto_embarque_sugerido_id = embarque
        viagem.ponto_destino_sugerido_id = desembarque
        viagem.precisa_escolher_ponto = embarque is None or desembarque is None

    return viagens


def _ponto_da_instituicao(aluno: Aluno) -> Any:
    if aluno.instituicao is None:
        return None
    return aluno.instituicao.ponto_id


def _ponto_da_instituicao_da_viagem(
    aluno: Aluno, horario: HorarioRota, data: dict[str, Any]
) -> Any:
    """Ponto da instituição desta viagem: a escolhida pelo aluno ou, sem escolha, a dele.

    O aluno pode pegar o transporte numa instituição que não é a sua. A escolhida precisa ter
    ponto e esse ponto precisa estar na rota da viagem.
    """
    instituicao_id = data.get("instituicao_id")
    if instituicao_id is None:
        rota = db.session.get(Rota, horario.rota_id)
        if rota is not None and rota.prefeitura_id != aluno.prefeitura_id:
            # Aluno de outro município não tem instituição própria nesta rota: precisa escolher uma.
            raise ValidationError(
                "Escolha a instituição da rota.", details={"field": "instituicao_id"}
            )
        return _ponto_da_instituicao(aluno)

    instituicao = db.session.get(Instituicao, instituicao_id)
    if instituicao is None or instituicao.ponto_id is None:
        raise ValidationError(
            "Instituição sem ponto de parada.", details={"field": "instituicao_id"}
        )
    na_rota = RotaPonto.query.filter_by(
        rota_id=horario.rota_id, ponto_id=instituicao.ponto_id
    ).first()
    if na_rota is None:
        raise ValidationError(
            "Esta instituição não faz parte da rota da viagem.", details={"field": "instituicao_id"}
        )
    return instituicao.ponto_id


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
    """Devolve (embarque, destino, escolhas do padrão antigo da rota).

    O aluno escolhe embarque e desembarque em qualquer sentido. O que ele não mandar vem, nesta
    ordem, do que ele lembrou para este horário e do padrão: na ida o desembarque é a instituição
    principal dele (ou a escolhida em `instituicao_id`), na volta o embarque é ela.
    """
    sentido = horario.sentido
    lembrado = db.session.get(PadraoPontosAluno, (aluno.usuario_id, horario.id))
    escolhas: dict[str, Any] = {}

    def ponto_da_instituicao() -> Any:
        ponto = _ponto_da_instituicao_da_viagem(aluno, horario, data)
        if ponto is None:
            raise ValidationError(
                "Seu cadastro não tem instituição com ponto de parada. Fale com o gestor.",
                details={"field": "instituicao_id"},
            )
        return ponto

    # Instituição escolhida na hora vale mais que o ponto lembrado.
    instituicao_na_hora = data.get("instituicao_id") is not None
    # O ponto da instituição, quando vem do cadastro, não precisa estar na rota (como sempre foi).
    confere_embarque = True
    confere_destino = True

    embarque = data.get("ponto_embarque_id")
    if embarque is not None and sentido != SentidoViagem.VOLTA:
        escolhas["ponto_embarque_padrao_id"] = embarque
    if embarque is None and sentido == SentidoViagem.VOLTA and instituicao_na_hora:
        embarque = ponto_da_instituicao()
        confere_embarque = False
    if embarque is None and lembrado is not None:
        embarque = lembrado.ponto_embarque_id
    if embarque is None:
        if sentido == SentidoViagem.VOLTA:
            embarque = ponto_da_instituicao()
            confere_embarque = False
        else:
            embarque = inscricao.ponto_embarque_padrao_id

    if confere_embarque:
        embarque = _ponto_da_rota(horario.rota_id, embarque, "ponto_embarque_id")

    destino = data.get("ponto_desembarque_id")
    if destino is not None and sentido != SentidoViagem.IDA:
        escolhas["ponto_desembarque_padrao_id"] = destino
    if destino is None and sentido == SentidoViagem.IDA and instituicao_na_hora:
        destino = ponto_da_instituicao()
        confere_destino = False
    if destino is None and lembrado is not None:
        destino = lembrado.ponto_desembarque_id
    if destino is None:
        if sentido == SentidoViagem.IDA:
            destino = ponto_da_instituicao()
            confere_destino = False
        else:
            destino = inscricao.ponto_desembarque_padrao_id

    if confere_destino:
        destino = _ponto_da_rota(horario.rota_id, destino, "ponto_desembarque_id")
    if embarque == destino:
        raise ValidationError(
            "Embarque e desembarque precisam ser pontos diferentes",
            details={"field": "ponto_desembarque_id"},
        )
    return embarque, destino, escolhas


def _lembrar_pontos_do_horario(aluno_id: Any, horario_id: Any, embarque: Any, destino: Any) -> None:
    padrao = db.session.get(PadraoPontosAluno, (aluno_id, horario_id))
    if padrao is None:
        padrao = PadraoPontosAluno(aluno_id=aluno_id, horario_rota_id=horario_id)
        db.session.add(padrao)
    padrao.ponto_embarque_id = embarque
    padrao.ponto_desembarque_id = destino


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
        if confirmacao and viagem.status == StatusViagem.CANCELADA:
            raise ValidationError("Esta viagem foi cancelada")

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
                _lembrar_pontos_do_horario(aluno.usuario_id, horario.id, embarque, destino)
        else:
            estava_confirmado = bool(registro.confirmacao)
            embarque_que_tinha = registro.ponto_embarque_id
            destino_que_tinha = registro.ponto_destino_id
            registro.confirmacao = False
            registro.ponto_embarque_id = None
            registro.ponto_destino_id = None
            if estava_confirmado:
                _avisar_motorista_do_cancelamento(
                    viagem, aluno.usuario_id, embarque_que_tinha, destino_que_tinha
                )

        return registro


def _avisar_motorista_do_cancelamento(
    viagem: Viagem, aluno_id: Any, embarque_id: Any, destino_id: Any
) -> None:
    """Avisa o motorista que um aluno confirmado cancelou. Se era o único a usar um ponto de
    embarque ou desembarque, diz que a parada pode ser pulada. Só vale antes de a viagem acabar."""
    if viagem.motorista_id is None:
        return
    if viagem.status not in (StatusViagem.AGENDADA, StatusViagem.EM_ANDAMENTO):
        return

    usuario = db.session.get(User, aluno_id)
    nome = usuario.nome if usuario else "Um aluno"
    hora = viagem.horario_rota.horario_saida.strftime("%H:%M")
    mensagem = f"{nome} cancelou a presença na viagem das {hora}."

    restantes = AlunosConfirmados.query.filter(
        AlunosConfirmados.viagem_id == viagem.id,
        AlunosConfirmados.confirmacao.is_(True),
        AlunosConfirmados.aluno_id != aluno_id,
    ).all()
    ainda_usados = set()
    for conf in restantes:
        ainda_usados.add(conf.ponto_embarque_id)
        ainda_usados.add(conf.ponto_destino_id)

    sem_ninguem: list[str] = []
    for ponto_id in (embarque_id, destino_id):
        if ponto_id is None or ponto_id in ainda_usados:
            continue
        ponto = db.session.get(Ponto, ponto_id)
        if ponto and ponto.apelido not in sem_ninguem:
            sem_ninguem.append(ponto.apelido)
    if sem_ninguem:
        mensagem += f" Ninguém mais usa {', '.join(sem_ninguem)}: a parada pode ser pulada."

    NotificacaoService._criar_notificacao_interna(
        usuario_id=viagem.motorista_id,
        titulo="Aluno cancelou a presença",
        mensagem=mensagem,
    )


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


def list_viagens_motorista(
    user_id: str,
    limit: int = 100,
    offset: int = 0,
    periodo: str | None = None,
    viagem_id: Any = None,
    rota_id: Any = None,
) -> list[Viagem]:
    """Viagens do motorista, em páginas.

    `periodo="proximas"`: em andamento, mais agendadas e canceladas de ontem em diante (ontem
    ainda pode estar aberta), da mais perto para a mais longe. `periodo="historico"`: feitas,
    canceladas e agendadas de dias que já passaram, da mais recente para a mais antiga. Sem
    `periodo` vem tudo, da mais recente para a mais antiga. `viagem_id` restringe a uma viagem
    (sempre só entre as do próprio motorista).
    """
    hoje = date.today()
    ainda_aberta = and_(
        Viagem.status.in_([StatusViagem.AGENDADA, StatusViagem.CANCELADA]),
        Viagem.data >= hoje - timedelta(days=1),
    )
    ja_passou = or_(
        Viagem.status.in_([StatusViagem.FINALIZADA, StatusViagem.CANCELADA]),
        and_(Viagem.status == StatusViagem.AGENDADA, Viagem.data < hoje),
    )

    query = (
        db.session.query(Viagem)
        .join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
        .options(*_carga_da_listagem())
        .filter(Viagem.motorista_id == user_id)
    )
    if viagem_id is not None:
        query = query.filter(Viagem.id == viagem_id)
    if rota_id is not None:
        query = query.filter(HorarioRota.rota_id == rota_id)

    if periodo == "proximas":
        query = query.filter(or_(Viagem.status == StatusViagem.EM_ANDAMENTO, ainda_aberta)).order_by(
            Viagem.data.asc(), HorarioRota.horario_saida.asc(), Viagem.id.asc()
        )
    else:
        if periodo == "historico":
            query = query.filter(ja_passou)
        query = query.order_by(
            Viagem.data.desc(), HorarioRota.horario_saida.desc(), Viagem.id.desc()
        )

    return query.offset(offset).limit(limit).all()


def _exigir_viagem_da_prefeitura(user: User, viagem: Viagem) -> None:
    """404 quando a viagem não é da prefeitura do usuário (a dona é a da rota)."""
    if viagem.horario_rota is None or viagem.horario_rota.rota.prefeitura_id != user.prefeitura_id:
        raise NotFoundError("Viagem não encontrada")


def calcular_km_percorrido(viagem_id: Any) -> float:
    """Soma a distância entre os pontos de GPS da viagem, em km."""
    rastros = (
        TelemetriaViagem.query.filter_by(viagem_id=viagem_id)
        .order_by(TelemetriaViagem.timestamp.asc())
        .all()
    )

    distancia_metros = 0.0
    for i in range(len(rastros) - 1):
        p1 = rastros[i]
        p2 = rastros[i + 1]
        distancia_metros += calcular_distancia_metros(
            float(p1.latitude), float(p1.longitude), float(p2.latitude), float(p2.longitude)
        )
    return round(distancia_metros / 1000.0, 2)


def controlar_viagem(user_id: str, viagem_id: str, data: dict[str, Any]) -> Viagem:
    """Start or finish a trip. Expects schema-validated payload with 'acao'."""
    user = db.session.get(User, user_id)
    viagem = db.session.get(Viagem, viagem_id)

    if not user:
        raise NotFoundError("Usuário não encontrado")

    if not viagem:
        raise NotFoundError("Viagem não encontrada")

    if user.role not in (UserRole.MOTORISTA, UserRole.GESTOR):
        raise ForbiddenError("Apenas motoristas ou gestores podem iniciar ou finalizar viagens")
    _exigir_viagem_da_prefeitura(user, viagem)
    if user.role == UserRole.MOTORISTA and viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")

    acao = data.get("acao")

    with transactional():
        if acao == "INICIAR":
            # O ônibus pode ser consertado a tempo: iniciar a viagem cancelada de hoje desfaz o
            # cancelamento. Cancelada de outro dia continua recusada.
            era_cancelada = viagem.status == StatusViagem.CANCELADA
            if era_cancelada and viagem.data != date.today():
                raise ValidationError("Só dá para retomar uma viagem cancelada no próprio dia")
            if viagem.status not in (StatusViagem.AGENDADA, StatusViagem.CANCELADA):
                raise ValidationError(
                    f"Não é possível iniciar viagem com status {viagem.status.name}"
                )
            if viagem.data > date.today():
                raise ValidationError("A viagem só pode ser iniciada no dia dela")
            viagem.status = StatusViagem.EM_ANDAMENTO
            viagem.inicio_real = datetime.now(UTC)

            if era_cancelada:
                viagem.motivo_cancelamento = None
                hora = viagem.horario_rota.horario_saida.strftime("%H:%M")
                for aluno_id in _alunos_da_viagem_a_avisar(viagem):
                    NotificacaoService._criar_notificacao_interna(
                        usuario_id=aluno_id,
                        titulo="Viagem retomada",
                        mensagem=f"A viagem de hoje às {hora} voltou a acontecer e o ônibus já saiu.",
                    )

            NotificacaoService.notificar_alunos_viagem_iniciada(viagem_id=viagem_id)

        elif acao == "FINALIZAR":
            if viagem.status != StatusViagem.EM_ANDAMENTO:
                raise ValidationError("A viagem precisa estar em andamento para ser finalizada")
            viagem.status = StatusViagem.FINALIZADA
            viagem.fim_real = datetime.now(UTC)

            viagem.km_real = calcular_km_percorrido(viagem.id)
        elif acao == "MARCAR_REALIZADA":
            # Viagem que passou do horário sem ser registrada no app: o motorista confirma que foi feita.
            cancelada_pelo_prazo = (
                viagem.status == StatusViagem.CANCELADA
                and viagem.motivo_cancelamento == MOTIVO_NAO_REALIZADA
            )
            if viagem.status != StatusViagem.AGENDADA and not cancelada_pelo_prazo:
                raise ValidationError("Só uma viagem agendada pode ser marcada como realizada")
            saida = datetime.combine(viagem.data, viagem.horario_rota.horario_saida)
            if saida > datetime.now():
                raise ValidationError("A viagem ainda não começou")
            viagem.status = StatusViagem.FINALIZADA
            viagem.motivo_cancelamento = None
            viagem.realizada_sem_app = True
        else:
            raise ValidationError("Ação inválida. Use INICIAR, FINALIZAR ou MARCAR_REALIZADA")

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


def adicionar_ponto_na_viagem(user_id: str, viagem_id: str, data: dict[str, Any]) -> Viagem:
    """Motorista acrescenta uma parada só nesta viagem em andamento (a rota não muda)."""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.MOTORISTA:
        raise ForbiddenError("Apenas motoristas podem adicionar pontos à viagem")

    viagem = db.session.get(Viagem, viagem_id)
    if viagem is None or viagem.horario_rota is None:
        raise NotFoundError("Viagem não encontrada")
    if viagem.horario_rota.rota.prefeitura_id != user.prefeitura_id:
        raise NotFoundError("Viagem não encontrada")
    if viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")
    if viagem.status != StatusViagem.EM_ANDAMENTO:
        raise ValidationError("A viagem precisa estar em andamento para receber novos pontos")

    with transactional():
        if "ponto_id" in data:
            ponto = db.session.get(Ponto, data["ponto_id"])
            if ponto is None or ponto.prefeitura_id != user.prefeitura_id:
                raise NotFoundError("Ponto não encontrado")
        else:
            ponto = Ponto(
                prefeitura_id=user.prefeitura_id,
                apelido=data.get("apelido") or "Parada extra",
                latitude=data["latitude"],
                longitude=data["longitude"],
            )
            db.session.add(ponto)
            db.session.flush()

        # A chave de ViagemPonto é (viagem, ponto): o mesmo ponto não entra duas vezes (409).
        for parada in viagem.pontos_visitados:
            if parada.ponto_id == ponto.id:
                raise ConflictError("Este ponto já faz parte da viagem")

        if data.get("posicao", "proxima") == "fim":
            nova_ordem = len(viagem.pontos_visitados) + 1
        else:
            # Logo depois da última parada visitada; as não visitadas descem uma posição.
            ultima_visitada = 0
            for parada in viagem.pontos_visitados:
                if parada.visitado and parada.ordem > ultima_visitada:
                    ultima_visitada = parada.ordem
            nova_ordem = ultima_visitada + 1
            for parada in viagem.pontos_visitados:
                if parada.ordem >= nova_ordem:
                    parada.ordem += 1

        db.session.add(
            ViagemPonto(viagem_id=viagem.id, ponto_id=ponto.id, ordem=nova_ordem, visitado=False)
        )

    db.session.refresh(viagem)
    audit_logger.log_user_action(
        action="adicionar_ponto_na_viagem",
        user_id=user_id,
        resource_type="viagem",
        resource_id=viagem_id,
    )
    return viagem


# Chegada "auto" vem do GPS do aparelho: só vale perto do ponto.
DISTANCIA_MAX_CHEGADA_AUTO_M = 150
# Chegada antiga já não serve de aviso aos alunos; só atualiza o progresso.
JANELA_AVISO_CHEGADA = timedelta(minutes=10)
TOLERANCIA_RELOGIO = timedelta(minutes=5)
IDADE_MAXIMA_CHEGADA = timedelta(hours=24)


def _motivo_de_rejeicao_da_chegada(
    evento: dict[str, Any], paradas: dict[Any, ViagemPonto], agora: datetime
) -> str | None:
    """Devolve por que o evento não pode ser aceito, ou None quando está tudo certo."""
    parada = paradas.get(evento["ponto_id"])
    if parada is None:
        return "ponto_fora_da_viagem"
    if evento["detectado_em"] > agora + TOLERANCIA_RELOGIO:
        return "horario_no_futuro"
    if evento["detectado_em"] < agora - IDADE_MAXIMA_CHEGADA:
        return "horario_muito_antigo"
    if evento["origem"] == "auto":
        if "latitude" not in evento or "longitude" not in evento:
            return "sem_posicao"
        distancia = calcular_distancia_metros(
            float(evento["latitude"]),
            float(evento["longitude"]),
            float(parada.ponto.latitude),
            float(parada.ponto.longitude),
        )
        if distancia > DISTANCIA_MAX_CHEGADA_AUTO_M:
            return "longe_do_ponto"
    return None


def registrar_chegadas(user_id: str, viagem_id: str, eventos: list[dict[str, Any]]) -> dict:
    """Marca os pontos que o app do motorista viu o ônibus alcançar, em lote.

    Idempotente: repetir um evento não muda nada, e vale a chegada mais antiga. Aceita
    viagem em andamento ou finalizada, porque o app pode enviar a fila depois do fim.
    """
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.MOTORISTA:
        raise ForbiddenError("Apenas motoristas podem registrar chegadas")

    viagem = db.session.get(Viagem, viagem_id)
    if viagem is None or viagem.horario_rota is None:
        raise NotFoundError("Viagem não encontrada")
    if viagem.horario_rota.rota.prefeitura_id != user.prefeitura_id:
        raise NotFoundError("Viagem não encontrada")
    if viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")
    if viagem.status not in (StatusViagem.EM_ANDAMENTO, StatusViagem.FINALIZADA):
        raise ValidationError("A viagem precisa estar em andamento ou finalizada")

    paradas: dict[Any, ViagemPonto] = {}
    for parada in viagem.pontos_visitados:
        paradas[parada.ponto_id] = parada

    agora = datetime.now(UTC)
    aceitos: list[str] = []
    rejeitados: list[dict[str, str]] = []
    novas: list[tuple[ViagemPonto, datetime]] = []

    with transactional():
        for evento in eventos:
            if evento["detectado_em"].tzinfo is None:
                evento["detectado_em"] = evento["detectado_em"].replace(tzinfo=UTC)
            motivo = _motivo_de_rejeicao_da_chegada(evento, paradas, agora)
            if motivo is not None:
                rejeitados.append({"ponto_id": str(evento["ponto_id"]), "motivo": motivo})
                continue

            parada = paradas[evento["ponto_id"]]
            aceitos.append(str(evento["ponto_id"]))
            if parada.visitado and parada.chegada_real is not None:
                if evento["detectado_em"] < parada.chegada_real:
                    parada.chegada_real = evento["detectado_em"]
                continue
            parada.visitado = True
            parada.chegada_real = evento["detectado_em"]
            parada.origem_chegada = evento["origem"]
            if evento["origem"] != "conferencia":
                novas.append((parada, evento["detectado_em"]))

    # Só avisa quem está esperando agora: chegada antiga ou viagem encerrada não gera aviso.
    if viagem.status == StatusViagem.EM_ANDAMENTO:
        for parada, detectado_em in novas:
            if agora - detectado_em > JANELA_AVISO_CHEGADA:
                continue
            esperando = AlunosConfirmados.query.filter_by(
                viagem_id=viagem.id,
                confirmacao=True,
                ponto_embarque_id=parada.ponto_id,
                embarcou=False,
            ).all()
            for conf in esperando:
                NotificacaoService._criar_notificacao_interna(
                    usuario_id=conf.aluno_id,
                    titulo="🚌 O ônibus chegou ao seu ponto",
                    mensagem=f"O ônibus está no seu ponto de embarque ({parada.ponto.apelido}).",
                )
        db.session.commit()

    audit_logger.log_user_action(
        action="registrar_chegadas",
        user_id=user_id,
        resource_type="viagem",
        resource_id=viagem_id,
    )
    return {"aceitos": aceitos, "rejeitados": rejeitados}


def _alunos_da_viagem_a_avisar(viagem: Viagem) -> list[Any]:
    """Todos os alunos inscritos na rota da viagem, mais quem confirmou e já saiu da rota."""
    ids: list[Any] = []
    for inscricao in RotaAluno.query.filter_by(rota_id=viagem.horario_rota.rota_id).all():
        ids.append(inscricao.aluno_id)
    for conf in AlunosConfirmados.query.filter_by(viagem_id=viagem.id, confirmacao=True).all():
        if conf.aluno_id not in ids:
            ids.append(conf.aluno_id)
    return ids


def cancelar_viagem(user_id: str, viagem_id: str, motivo: str | None = None) -> dict[str, Any]:
    """Cancela uma viagem. Gestor cancela qualquer uma da prefeitura; motorista, só a sua.

    Todos os alunos inscritos na rota são avisados, tenham confirmado ou não, e o motivo fica
    gravado na viagem para o aluno ver ao abrir. Quem não cancelou também é avisado: o motorista
    quando o gestor cancela, e os gestores da prefeitura quando o motorista cancela.
    """
    user = db.session.get(User, user_id)
    if not user or user.role not in (UserRole.GESTOR, UserRole.MOTORISTA):
        raise ForbiddenError("Apenas gestores e motoristas podem cancelar viagens")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")
    _exigir_viagem_da_prefeitura(user, viagem)
    if user.role == UserRole.MOTORISTA and viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")

    if viagem.status in (StatusViagem.FINALIZADA, StatusViagem.CANCELADA):
        raise ValidationError(f"Não é possível cancelar uma viagem com status {viagem.status.name}")

    with transactional():
        viagem.status = StatusViagem.CANCELADA
        viagem.motivo_cancelamento = motivo or None

        alunos_a_avisar = _alunos_da_viagem_a_avisar(viagem)
        data_formatada = viagem.data.strftime("%d/%m/%Y")
        hora_formatada = viagem.horario_rota.horario_saida.strftime("%H:%M")
        quem = "pelo motorista" if user.role == UserRole.MOTORISTA else "pela prefeitura"
        sufixo_motivo = f" Motivo: {motivo}." if motivo else ""

        for aluno_id in alunos_a_avisar:
            NotificacaoService._criar_notificacao_interna(
                usuario_id=aluno_id,
                titulo="Viagem Cancelada",
                mensagem=(
                    f"Atenção! A viagem da rota agendada para o dia {data_formatada} "
                    f"foi cancelada {quem}.{sufixo_motivo}"
                ),
            )

        texto_aviso = (
            f"A viagem de {data_formatada} às {hora_formatada} foi cancelada {quem}.{sufixo_motivo}"
        )
        if user.role == UserRole.GESTOR:
            if viagem.motorista_id:
                NotificacaoService._criar_notificacao_interna(
                    usuario_id=str(viagem.motorista_id),
                    titulo="Viagem Cancelada",
                    mensagem=texto_aviso,
                )
        else:
            gestores = User.query.filter_by(
                prefeitura_id=user.prefeitura_id, role=UserRole.GESTOR
            ).all()
            for gestor in gestores:
                NotificacaoService._criar_notificacao_interna(
                    usuario_id=str(gestor.id),
                    titulo="Viagem Cancelada",
                    mensagem=f"{user.nome} cancelou: {texto_aviso}",
                )

    audit_logger.log_user_action(
        action="cancelar_viagem", user_id=user_id, resource_type="viagem", resource_id=viagem_id
    )

    return {"message": "Viagem cancelada com sucesso", "alunos_notificados": len(alunos_a_avisar)}


def _info_observadores(viagem: Viagem, agora: datetime) -> dict:
    """Diz ao motorista se alguém consultou a posição dentro da janela."""
    solicitada = viagem.localizacao_solicitada_em
    observadores = False
    if solicitada is not None:
        idade = (agora - solicitada).total_seconds()
        observadores = idade <= JANELA_OBSERVADOR_SEGUNDOS
    if observadores:
        intervalo = INTERVALO_COM_OBSERVADOR
    else:
        intervalo = INTERVALO_SEM_OBSERVADOR
    return {"observadores": observadores, "intervalo_sugerido_segundos": intervalo}


def _pedir_localizacao_ao_motorista(viagem: Viagem) -> None:
    motorista = db.session.get(User, viagem.motorista_id) if viagem.motorista_id else None
    if motorista is None:
        return
    NotificacaoService.enviar_push_so_dados(
        motorista,
        {"tipo": "demanda_localizacao", "viagem_id": str(viagem.id)},
        collapse_key=f"demanda_localizacao_{viagem.id}",
    )


def atualizar_localizacao(user_id: str, viagem_id: str, data: dict) -> dict:
    """Atualiza o GPS do motorista, salva telemetria e engatilha o Auto-Checkin."""
    user = db.session.get(User, user_id)
    if not user or user.role != UserRole.MOTORISTA:
        raise ForbiddenError("Apenas motoristas podem enviar localização em tempo real")

    viagem = db.session.get(Viagem, viagem_id)
    if not viagem:
        raise NotFoundError("Viagem não encontrada")
    _exigir_viagem_da_prefeitura(user, viagem)
    if viagem.motorista_id != user.id:
        raise ForbiddenError("Esta viagem não pertence a você")

    if viagem.status != StatusViagem.EM_ANDAMENTO:
        raise ValidationError(f"A viagem não está em andamento (Status: {viagem.status.name})")

    agora = datetime.now(UTC)
    observadores = _info_observadores(viagem, agora)

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
        return {
            "message": "Todos os pontos já foram visitados. Viagem quase concluída!",
            **observadores,
        }

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
            **observadores,
        }

    return {
        "message": "Localização atualizada silenciosamente com telemetria.",
        "distancia_metros": int(distancia_metros),
        **observadores,
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

    # A consulta do próprio motorista não conta como observador.
    if user.role != UserRole.MOTORISTA:
        agora = datetime.now(UTC)
        eram_observadores = _info_observadores(viagem, agora)["observadores"]
        viagem.localizacao_solicitada_em = agora
        db.session.commit()
        # Transição sem observador -> com observador: acorda o app do motorista.
        if not eram_observadores:
            _pedir_localizacao_ao_motorista(viagem)

    # Paradas em que o motorista já chegou (confirmadas por ele ou detectadas): o app do aluno usa
    # isto para saber qual é a próxima parada, sem pedir outra rota.
    pontos_visitados: list[str] = []
    for parada in viagem.pontos_visitados:
        if parada.visitado:
            pontos_visitados.append(str(parada.ponto_id))

    return {
        "latitude": float(viagem.motorista_lat) if viagem.motorista_lat is not None else None,
        "longitude": float(viagem.motorista_lon) if viagem.motorista_lon is not None else None,
        "atualizado_em": (
            viagem.motorista_gps_hora.isoformat() if viagem.motorista_gps_hora else None
        ),
        "pontos_visitados": pontos_visitados,
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
