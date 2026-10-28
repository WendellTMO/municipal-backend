import atexit
import os

from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from flask_apscheduler import APScheduler

from app.tasks.agendamento_tasks import job_gerar_viagens_semanais
from app.tasks.convite_tasks import job_convites
from app.tasks.notificacao_tasks import verificar_viagens_10min, verificar_viagens_24h


def init_scheduler(app: Flask, scheduler: APScheduler):
    """Inicializa o APScheduler.

    Roda em todo processo, não só no dedicado. `add_job()` é chamado de fora
    daqui, no auto-checkin por proximidade (`viagens_service.py`,
    `viagem_tasks.py`), disparado durante o request de um worker da API. Sem
    o scheduler "started" nesse processo, `add_job()` só empilha numa lista
    de pending jobs local que nunca é lida, e o job nunca chega no jobstore
    compartilhado (`SQLAlchemyJobStore`, configurado em `configure_app`).

    Só o processo com RUN_SCHEDULER ligado registra os jobs periódicos e
    processa jobs de verdade. Os demais (workers da API, `app.scheduler_main`
    desligado, suíte de testes) sobem pausados: `add_job`/`get_job`
    funcionam contra o jobstore compartilhado, `_process_jobs` nunca roda.
    Isso também resolve a duplicação entre os 4 workers do gunicorn: só o
    processo dedicado com RUN_SCHEDULER ligado alguma vez processa um job
    devido, os workers só gravam.
    """
    run_scheduler = os.getenv("RUN_SCHEDULER", "").lower() in ("1", "true")

    if run_scheduler:
        # Sem `args=[app]`: o jobstore agora é o SQLAlchemyJobStore, que
        # serializa o job via pickle pra gravar no Postgres. O objeto Flask
        # `app` carrega closures internas que não picklam. As três tasks
        # buscam `scheduler.app` por dentro, como `realizar_auto_checkin`
        # já fazia em `viagem_tasks.py`.
        scheduler.add_job(
            id="job_24h",
            func=verificar_viagens_24h,
            trigger="interval",
            minutes=60,
            replace_existing=True,
        )

        scheduler.add_job(
            id="job_10min",
            func=verificar_viagens_10min,
            trigger="interval",
            minutes=10,
            replace_existing=True,
        )

        # Sem `args=[app]` pelo mesmo motivo: o job usa `scheduler.app`.
        scheduler.add_job(
            id="job_convites",
            func=job_convites,
            trigger="interval",
            minutes=1,
            max_instances=1,
            replace_existing=True,
        )

        # Diário, e não semanal: a geração é idempotente e cobre 14 dias à
        # frente, então rodar todo dia recupera sozinho de uma execução
        # perdida.
        scheduler.add_job(
            id="job_viagens_semanais",
            func=job_gerar_viagens_semanais,
            trigger=CronTrigger(hour=2, minute=0, timezone="America/Sao_Paulo"),
            replace_existing=True,
        )
    else:
        app.logger.info("RUN_SCHEDULER desligado: nenhum job periódico registrado neste processo.")

    scheduler.start(paused=not run_scheduler)

    atexit.register(lambda: scheduler.running and scheduler.shutdown())
