import json
import logging
import os
from datetime import timedelta
from typing import Any

import firebase_admin
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from dotenv import load_dotenv
from firebase_admin import credentials
from flask import Flask, Response, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_restx import Api

from app.core.error_handlers import register_error_handlers, register_jwt_handlers
from app.extensions import scheduler
from app.utils.scheduler_setup import init_scheduler

from .api.controllers.aluno_controller import api as alunos_ns
from .api.controllers.auth_controller import api as auth_ns
from .api.controllers.dashboard_controller import api as dashboard_ns
from .api.controllers.feedback_controller import api as feedback_ns
from .api.controllers.instituicao_controller import api as inst_ns
from .api.controllers.notificacao_controller import api as notificacoes_ns
from .api.controllers.ocorrencia_controller import api as ocorrencias_ns
from .api.controllers.onibus_controller import api as onibus_ns
from .api.controllers.pontos_controller import api as pontos_ns
from .api.controllers.rotas_controller import api as rotas_ns
from .api.controllers.routing_controller import api as routing_ns
from .api.controllers.user_controller import api as user_ns
from .api.controllers.viagens_controller import api as viagem_ns
from .core.config import Settings
from .models import Ocorrencia  # noqa: F401 — registers table with SQLAlchemy
from .models.base import db
from .utils import (
    check_production_security,
    setup_logging,
    setup_request_id_middleware,
    setup_security_headers,
)

jwt = JWTManager()
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    load_dotenv()
    settings = Settings()
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # A ordem das chamadas abaixo é a mesma da versão anterior desta função e
    # não deve ser alterada: o registro dos namespaces define o app.url_map.
    init_firebase(settings)
    configure_app(app, settings)
    register_extensions(app, settings)
    register_scheduler(app)
    configure_security(app, settings)

    api = register_blueprints(app)

    register_handlers(app)
    register_openapi_routes(app, api)
    register_health_routes(app, settings)

    return app


# ==========================================
# create_app() helpers (registration order above)
# ==========================================

API_DESCRIPTION = """
## Sistema de Gerenciamento de Transporte Escolar

API para gerenciamento de rotas, viagens e alunos do transporte escolar municipal.

### Autenticação
Todos os endpoints (exceto `/auth/login`) requerem autenticação JWT.
Inclua o header: `Authorization: Bearer <seu_token>`

### Roles
- **ALUNO**: Visualiza rotas, confirma presença em viagens
- **MOTORISTA**: Gerencia viagens atribuídas, inicia/finaliza trajetos
- **GESTOR**: Acesso completo à prefeitura (CRUD de rotas, motoristas, relatórios)
        """

AUTHORIZATIONS = {
    "Bearer": {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
        "description": "JWT token. Format: Bearer <token>",
    }
}

# Ordem preservada da montagem original: qualquer mudança aqui altera o
# app.url_map, que é contrato público consumido pelo frontend.
NAMESPACES = (
    (auth_ns, "/v1/auth"),
    (user_ns, "/v1/users"),
    (notificacoes_ns, "/v1/notificacoes"),
    (onibus_ns, "/v1/onibus"),
    (rotas_ns, "/v1/rotas"),
    (pontos_ns, "/v1/pontos"),
    (routing_ns, "/v1/routing"),
    (viagem_ns, "/v1/viagens"),
    (inst_ns, "/v1/instituicoes"),
    (alunos_ns, "/v1/alunos"),
    (ocorrencias_ns, "/v1/ocorrencias"),
    (dashboard_ns, "/v1/dashboard"),
    (feedback_ns, "/v1/feedback"),
)


def init_firebase(settings: Settings) -> None:
    """Inicializa o Firebase Admin SDK, se ainda não estiver inicializado."""
    if firebase_admin._apps:
        return

    if settings.FIREBASE_CREDENTIALS:
        cert_dict = json.loads(settings.FIREBASE_CREDENTIALS)
        cred = credentials.Certificate(cert_dict)
        logger.info("Firebase initialized via GitHub Secrets (Environment Variable).")
        firebase_admin.initialize_app(cred)
    else:
        if settings.DEBUG and not os.path.exists("firebase-credentials.json"):
            logger.warning("Firebase credentials not found in environment variables.")
        else:
            cred = credentials.Certificate("firebase-credentials.json")
            logger.info("Firebase initialized via local file.")
            firebase_admin.initialize_app(cred)


def configure_app(app: Flask, settings: Settings) -> None:
    """Aplica no app.config os valores derivados do Settings."""
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=settings.JWT_EXPIRES_HOURS)
    app.config["DEBUG"] = settings.DEBUG

    # O flask_restx captura as exceções levantadas dentro dos Resources e
    # responde 500 genérico por conta própria; ele só delega para os
    # @app.errorhandler registrados abaixo quando PROPAGATE_EXCEPTIONS é
    # verdadeiro. Sem isso o valor cai para DEBUG or TESTING, ou seja, todo
    # erro de negócio (400, 401, 403, 404) virava 500 em produção.
    # As exceções inesperadas continuam cobertas pelo handler de Exception,
    # que devolve o 500 no formato padrão sem vazar traceback.
    app.config["PROPAGATE_EXCEPTIONS"] = True

    app.config["MAIL_SERVER"] = settings.MAIL_SERVER
    app.config["MAIL_PORT"] = settings.MAIL_PORT
    app.config["MAIL_USERNAME"] = settings.MAIL_USERNAME
    app.config["MAIL_PASSWORD"] = settings.MAIL_PASSWORD
    app.config["MAIL_USE_TLS"] = settings.MAIL_USE_TLS
    app.config["FRONTEND_URL"] = settings.FRONTEND_URL

    # Jobstore do APScheduler compartilhado via Postgres: o processo com
    # RUN_SCHEDULER ligado processa os jobs, os workers da API só gravam
    # (auto-checkin por proximidade). Sem isso cada processo tinha seu
    # próprio jobstore em memória, e um job criado num worker nunca era
    # visto pelo processo que efetivamente roda o scheduler.
    app.config["SCHEDULER_JOBSTORES"] = {
        "default": SQLAlchemyJobStore(url=settings.SQLALCHEMY_DATABASE_URI)
    }


def register_extensions(app: Flask, settings: Settings) -> None:
    """Logging, CORS e as extensões Flask (SQLAlchemy, JWT)."""
    # ==========================================
    # Logging Configuration
    # ==========================================
    setup_logging(app)
    setup_request_id_middleware(app)

    logger.info(
        "Application starting",
        extra={
            "environment": settings.ENV,
            "debug": settings.DEBUG,
        },
    )

    # ==========================================
    # CORS Configuration
    # ==========================================
    CORS(
        app,
        origins=settings.CORS_ORIGINS,
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        max_age=86400,  # Cache preflight for 24 hours
    )

    db.init_app(app)
    jwt.init_app(app)


def register_scheduler(app: Flask) -> None:
    """
    Registra o APScheduler.

    Os jobs só são agendados no processo com RUN_SCHEDULER ligado;
    quem decide isso é o init_scheduler.
    """
    # ==========================================
    # Scheduler Configuration
    # ==========================================
    scheduler.init_app(app)

    init_scheduler(app, scheduler)


def configure_security(app: Flask, settings: Settings) -> None:
    """Headers de segurança, limite de tamanho de request e checagem de produção."""
    # ==========================================
    # Security Headers
    # ==========================================
    setup_security_headers(app)

    # Set maximum request size (16MB)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    # Check production security
    if not settings.DEBUG:
        security_warnings = check_production_security(app)
        if security_warnings:
            logger.warning(
                "Security configuration warnings",
                extra={"warnings": security_warnings},
            )


def register_blueprints(app: Flask) -> Api:
    """Cria a Api do flask-restx e registra os namespaces da v1."""
    api = Api(
        app,
        title="BusKá API",
        version="1.0.0",
        description=API_DESCRIPTION,
        doc="/docs",
        authorizations=AUTHORIZATIONS,
        security="Bearer",
        contact="BusKá Team",
    )

    # API v1 routes
    for namespace, path in NAMESPACES:
        api.add_namespace(namespace, path=path)

    return api


def register_handlers(app: Flask) -> None:
    """Handlers de erro da aplicação e do flask-jwt-extended."""
    # ==========================================
    # Error Handlers
    # ==========================================

    register_jwt_handlers(jwt)
    register_error_handlers(app)


def register_openapi_routes(app: Flask, api: Api) -> None:
    """Endpoint e comando de CLI que exportam a especificação OpenAPI."""

    # ==========================================
    # OpenAPI Export Endpoint
    # ==========================================

    @app.route("/openapi.json")
    def openapi_spec() -> Any:
        """Export OpenAPI specification as JSON."""
        return jsonify(api.__schema__)

    # ==========================================
    # CLI Commands
    # ==========================================

    @app.cli.command("export-openapi")
    def export_openapi() -> None:
        """Export OpenAPI specification to docs/openapi.json."""
        with app.test_request_context():
            spec = api.__schema__
            output_path = "docs/openapi.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, indent=2, ensure_ascii=False)
            print(f"[*] OpenAPI spec exported to {output_path}")


def register_health_routes(app: Flask, settings: Settings) -> None:
    """Probes de liveness e readiness."""

    # ==========================================
    # Health / Readiness Endpoints
    # ==========================================

    @app.get("/health")
    def health() -> tuple[Response, int]:
        """Liveness probe — server is running."""
        return (
            jsonify(
                status="ok",
                service="buska-backend",
                environment=settings.ENV,
            ),
            200,
        )

    @app.get("/ready")
    def ready() -> tuple[Response, int]:
        """Readiness probe — server can handle requests (DB reachable)."""
        try:
            # Minimal DB check (safe + fast)
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok", ready=True), 200
        except Exception:
            logger.error("Readiness check failed", exc_info=True)
            return jsonify(status="error", ready=False), 503
