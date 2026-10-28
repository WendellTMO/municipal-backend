from pathlib import Path

import pytest
from flask import Flask
from flask_apscheduler import APScheduler

from app.utils.scheduler_setup import init_scheduler

REPO_ROOT = Path(__file__).parents[2]

# Variáveis que precisam chegar aos containers de produção. A ausência de
# FLASK_ENV foi a causa raiz do scheduler nunca ter rodado na VM.
ENV_OBRIGATORIAS = [
    "FLASK_ENV",
    "TZ",
    "RUN_SCHEDULER",
    "FIREBASE_CREDENTIALS",
    "CORS_ORIGINS",
    "FRONTEND_URL",
    "MAIL_SERVER",
]

JOBS_ESPERADOS = {"job_24h", "job_10min", "job_viagens_semanais", "job_convites"}


@pytest.fixture()
def scheduler_app():
    """App mínima e isolada: init_scheduler só usa app.logger e app.debug."""
    app = Flask("scheduler_test")
    app.config["SCHEDULER_API_ENABLED"] = False
    return app


@pytest.fixture()
def sched(scheduler_app):
    scheduler = APScheduler()
    scheduler.init_app(scheduler_app)
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_init_scheduler_registra_todos_os_jobs(scheduler_app, sched, monkeypatch):
    monkeypatch.setenv("RUN_SCHEDULER", "true")

    init_scheduler(scheduler_app, sched)

    assert {job.id for job in sched.get_jobs()} == JOBS_ESPERADOS


def test_init_scheduler_nao_registra_nada_sem_run_scheduler(scheduler_app, sched, monkeypatch):
    """Garante que os 4 workers da API (e a suíte de testes) não recebam os
    jobs periódicos (verificação de viagem, geração semanal)."""
    monkeypatch.delenv("RUN_SCHEDULER", raising=False)

    init_scheduler(scheduler_app, sched)

    assert sched.get_jobs() == []


def test_scheduler_pausado_ainda_grava_no_jobstore(scheduler_app, sched, monkeypatch):
    """B6: sem RUN_SCHEDULER o scheduler sobe pausado, não parado.

    `viagens_service.py` e `viagem_tasks.py` chamam `scheduler.add_job()`
    durante o request de um worker da API, fora daqui. Se o scheduler
    continuasse parado (como antes), esse `add_job()` só empilharia numa
    lista de pending jobs local, nunca lida, e o auto-checkin nunca
    disparava. Pausado, `add_job` grava de verdade no jobstore, só não
    processa jobs devidos.
    """
    monkeypatch.delenv("RUN_SCHEDULER", raising=False)
    # O flask_apscheduler tem sua própria trava de debug (lê FLASK_DEBUG do
    # ambiente, não app.config), pra não duplicar job quando o reloader do
    # Flask sobe dois processos. Suíte e CI setam FLASK_DEBUG=true, e algum
    # teste anterior nessa mesma sessão pode ter chamado create_app() e
    # carregado essa variável via load_dotenv(). Sem isso o .start() abaixo
    # vira no-op silencioso e o teste fica instável conforme a ordem.
    monkeypatch.delenv("FLASK_DEBUG", raising=False)

    init_scheduler(scheduler_app, sched)

    assert sched.running

    sched.add_job(id="prova-b6", func=lambda: None, trigger="date", run_date="2099-01-01")

    assert sched.get_job("prova-b6") is not None


def test_geracao_de_viagens_roda_todo_dia(scheduler_app, sched, monkeypatch):
    """Job idempotente com janela de 14 dias: diário se recupera de execução perdida."""
    monkeypatch.setenv("RUN_SCHEDULER", "true")

    init_scheduler(scheduler_app, sched)

    trigger = sched.get_job("job_viagens_semanais").trigger
    campos = {campo.name: str(campo) for campo in trigger.fields}
    assert campos["day_of_week"] == "*"
    assert campos["hour"] == "2"
    assert campos["minute"] == "0"
    assert str(trigger.timezone) == "America/Sao_Paulo"


def test_compose_de_producao_repassa_env_obrigatorias():
    # Leitura como texto, sem dependência de yaml. Trocar por yaml.safe_load
    # se um dia for preciso afirmar coisas por serviço.
    texto = (REPO_ROOT / "docker-compose.prod.yml").read_text()

    ausentes = [chave for chave in ENV_OBRIGATORIAS if f"{chave}:" not in texto]

    assert not ausentes, f"faltando em docker-compose.prod.yml: {ausentes}"


def test_compose_de_producao_tem_servico_scheduler():
    texto = (REPO_ROOT / "docker-compose.prod.yml").read_text()

    assert "buska_scheduler" in texto
    assert "app.scheduler_main" in texto
