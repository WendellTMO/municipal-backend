import logging
from typing import Any

from flask import g, jsonify, request
from flask_jwt_extended import JWTManager
from marshmallow.exceptions import ValidationError as MarshmallowValidationError
from werkzeug.exceptions import HTTPException

from app.core.exceptions import AppError, ValidationError
from app.models.base import db
from app.models.user import User

logger = logging.getLogger(__name__)


def _request_id() -> str | None:
    rid = getattr(g, "request_id", None)
    if isinstance(rid, str):
        return rid

    header = request.headers.get("X-Request-ID")
    if isinstance(header, str):
        return header

    return None


def _error_payload(*, code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": _request_id(),
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


def register_error_handlers(app) -> None:
    """
    Registers a single, consistent error contract for the whole API.
    Do NOT duplicate handlers in create_app.
    """

    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        logger.warning(
            "Application error code=%s status=%s path=%s method=%s request_id=%s",
            err.code,
            err.status_code,
            request.path,
            request.method,
            _request_id(),
            extra={
                "code": err.code,
                "status": err.status_code,
                "path": request.path,
                "method": request.method,
                "request_id": _request_id(),
                "details": getattr(err, "details", None),
            },
        )

        details = None
        if isinstance(err, ValidationError):
            details = err.details or None

        payload = _error_payload(code=err.code, message=err.message, details=details)
        if getattr(err, "field", None):
            payload["error"]["field"] = err.field

        return jsonify(payload), err.status_code

    @app.errorhandler(MarshmallowValidationError)
    def handle_marshmallow_validation_error(err: MarshmallowValidationError):
        # Marshmallow puts field errors in err.messages (dict) and optional info in err.valid_data
        details = err.messages if hasattr(err, "messages") else None

        logger.warning(
            "Marshmallow validation error path=%s method=%s request_id=%s",
            request.path,
            request.method,
            _request_id(),
            extra={
                "code": "VALIDATION_ERROR",
                "status": 400,
                "path": request.path,
                "method": request.method,
                "request_id": _request_id(),
                "details": details,
            },
        )

        return (
            jsonify(
                _error_payload(
                    code="VALIDATION_ERROR", message="Erro de validação", details=details
                )
            ),
            400,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        code = "HTTP_ERROR"
        message = err.description or "Erro HTTP"
        status = err.code or 500

        logger.warning(
            "HTTP exception",
            extra={
                "code": code,
                "status": status,
                "path": request.path,
                "method": request.method,
                "request_id": _request_id(),
            },
        )

        return jsonify(_error_payload(code=code, message=message)), status

    @app.errorhandler(Exception)
    def handle_unexpected_error(err: Exception):
        logger.exception(
            "Unhandled exception path=%s method=%s request_id=%s",
            request.path,
            request.method,
            _request_id(),
            extra={
                "path": request.path,
                "method": request.method,
                "request_id": _request_id(),
            },
        )

        return (
            jsonify(_error_payload(code="INTERNAL_ERROR", message="Erro interno do servidor")),
            500,
        )


def register_jwt_handlers(jwt: JWTManager) -> None:
    @jwt.unauthorized_loader
    def missing_token(reason: str):
        return (
            jsonify(
                _error_payload(
                    code="UNAUTHORIZED", message="Não autenticado", details={"reason": reason}
                )
            ),
            401,
        )

    @jwt.invalid_token_loader
    def invalid_token(reason: str):
        return (
            jsonify(
                _error_payload(
                    code="INVALID_TOKEN", message="Token inválido", details={"reason": reason}
                )
            ),
            422,
        )

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return jsonify(_error_payload(code="TOKEN_EXPIRED", message="Token expirado")), 401

    @jwt.token_in_blocklist_loader
    def sessao_anterior_a_troca_de_senha(jwt_header, jwt_payload) -> bool:
        """Token emitido antes da última troca de senha não vale mais.

        Compara em segundos inteiros: o token novo, emitido na mesma troca, continua valendo.
        """
        alterada_em = (
            db.session.query(User.senha_alterada_em).filter(User.id == jwt_payload["sub"]).scalar()
        )
        if alterada_em is None:
            return False
        return int(jwt_payload.get("iat", 0)) < int(alterada_em.timestamp())

    @jwt.revoked_token_loader
    def revoked_token(jwt_header, jwt_payload):
        return jsonify(_error_payload(code="TOKEN_REVOKED", message="Token revogado")), 401
