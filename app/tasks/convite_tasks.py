import logging

from app.extensions import scheduler
from app.services import convite_service

logger = logging.getLogger(__name__)


def job_convites():
    """Job de 1 minuto que envia os e-mails dos convites PENDENTES."""
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return

    with app.app_context():
        try:
            enviados = convite_service.processar_envios()
        except Exception:
            logger.exception("Erro no job de envio de convites.")
            return
        if enviados:
            logger.info("Job de convites: %s convite(s) enviado(s).", enviados)
