"""Vigia as viagens em andamento: avisa o motorista parado e encerra a que passou do teto."""

import logging
from datetime import UTC, datetime, timedelta

from app.extensions import scheduler
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.viagem import TelemetriaViagem, Viagem
from app.services.notificacao_service import NotificacaoService
from app.services.viagens_service import calcular_km_percorrido
from app.utils.geo_utils import calcular_distancia_metros

logger = logging.getLogger(__name__)

TETO_DA_VIAGEM = timedelta(hours=5)
TEMPO_PARADO = timedelta(minutes=15)
# O GPS oscila alguns metros com o ônibus parado: dentro desse raio conta como parado.
RAIO_PARADO_METROS = 100
# Com menos pontos que isso na janela o app mandou pouco sinal, e não dá para dizer que parou.
MINIMO_DE_PONTOS = 2


def _sem_movimento(viagem: Viagem, agora: datetime) -> bool:
    """Verdadeiro se, nos últimos 15 minutos, o ônibus não saiu do lugar ou não mandou sinal."""
    desde = agora - TEMPO_PARADO
    if viagem.inicio_real is None or viagem.inicio_real > desde:
        return False

    rastros = (
        TelemetriaViagem.query.filter(
            TelemetriaViagem.viagem_id == viagem.id, TelemetriaViagem.timestamp >= desde
        )
        .order_by(TelemetriaViagem.timestamp.asc())
        .all()
    )
    if not rastros:
        return True
    if len(rastros) < MINIMO_DE_PONTOS:
        return False

    ultimo = rastros[-1]
    for rastro in rastros:
        distancia = calcular_distancia_metros(
            float(rastro.latitude),
            float(rastro.longitude),
            float(ultimo.latitude),
            float(ultimo.longitude),
        )
        if distancia > RAIO_PARADO_METROS:
            return False
    return True


def _avisar_motorista(viagem: Viagem, titulo: str, mensagem: str) -> None:
    if viagem.motorista_id is None:
        return
    NotificacaoService._criar_notificacao_interna(
        usuario_id=viagem.motorista_id, titulo=titulo, mensagem=mensagem
    )


def _encerrar_pelo_teto(viagem: Viagem) -> None:
    viagem.status = StatusViagem.FINALIZADA
    viagem.fim_real = viagem.inicio_real + TETO_DA_VIAGEM
    viagem.km_real = calcular_km_percorrido(viagem.id)
    _avisar_motorista(
        viagem,
        "Viagem encerrada automaticamente",
        "Sua viagem passou de 5 horas em andamento e foi encerrada pelo sistema.",
    )


def vigiar_viagens_em_andamento(agora: datetime | None = None) -> dict[str, int]:
    """Encerra viagem com mais de 5 horas e avisa, uma vez, o motorista sem movimento há 15 minutos."""
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return {"encerradas": 0, "avisadas": 0}

    with app.app_context():
        agora = agora or datetime.now(UTC)
        em_andamento = Viagem.query.filter(Viagem.status == StatusViagem.EM_ANDAMENTO).all()

        encerradas = 0
        avisadas = 0
        for viagem in em_andamento:
            if viagem.inicio_real is None:
                continue
            if agora - viagem.inicio_real >= TETO_DA_VIAGEM:
                _encerrar_pelo_teto(viagem)
                encerradas += 1
                continue

            if not _sem_movimento(viagem, agora):
                viagem.aviso_parada_enviado = False
                continue
            if not viagem.aviso_parada_enviado:
                _avisar_motorista(
                    viagem,
                    "Seu ônibus está parado",
                    "Não vemos movimento há 15 minutos. Se a viagem já acabou, finalize ou cancele no app.",
                )
                viagem.aviso_parada_enviado = True
                avisadas += 1

        db.session.commit()
        if encerradas or avisadas:
            logger.info(
                "Vigia de viagens: %s encerrada(s) pelo teto, %s motorista(s) avisado(s).",
                encerradas,
                avisadas,
            )
        return {"encerradas": encerradas, "avisadas": avisadas}
