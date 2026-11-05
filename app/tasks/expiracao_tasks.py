import logging
from datetime import datetime, timedelta

from app.extensions import scheduler
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.viagem import Viagem

logger = logging.getLogger(__name__)

PRAZO_PARA_CANCELAR = timedelta(hours=24)
MOTIVO_NAO_REALIZADA = "Não realizada: passaram 24 horas da saída sem a viagem começar"


def cancelar_viagens_nao_realizadas(agora: datetime | None = None) -> int:
    """Cancela a viagem agendada que passou 24 horas da saída sem ser iniciada nem confirmada."""
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return 0

    with app.app_context():
        agora = agora or datetime.now()
        limite = agora - PRAZO_PARA_CANCELAR

        # Um dia a mais na busca cobre a saída de ontem; a hora exata é conferida no loop.
        candidatas = Viagem.query.filter(
            Viagem.status == StatusViagem.AGENDADA,
            Viagem.data <= limite.date(),
        ).all()

        canceladas = 0
        for viagem in candidatas:
            if not viagem.horario_rota:
                continue
            saida = datetime.combine(viagem.data, viagem.horario_rota.horario_saida)
            if saida > limite:
                continue
            viagem.status = StatusViagem.CANCELADA
            viagem.motivo_cancelamento = MOTIVO_NAO_REALIZADA
            canceladas += 1

        if canceladas:
            db.session.commit()
            logger.info("Job de expiração: %s viagem(ns) cancelada(s) por não realização.", canceladas)
        return canceladas
