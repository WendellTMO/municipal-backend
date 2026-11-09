import logging

from app.extensions import scheduler
from app.services import telemetria_service

logger = logging.getLogger(__name__)


def job_limpar_telemetria():
    """Job diário: apaga os eventos de uso com mais de 90 dias."""
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return

    with app.app_context():
        try:
            apagados = telemetria_service.apagar_eventos_antigos()
        except Exception:
            logger.exception("Erro no job de limpeza da telemetria.")
            return
        if apagados:
            logger.info("Job de telemetria: %s evento(s) com mais de 90 dias apagado(s).", apagados)
