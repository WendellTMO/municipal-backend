from typing import Any

from flask import current_app, request
from flask_restx import Namespace, Resource

from app.api.contracts import auth_contract
from app.core.exceptions import ValidationError
from app.schemas.auth_schema import LoginRequestSchema, TokenResponseSchema
from app.services import auth_service

api = Namespace("auth", description="Autenticação e gerenciamento de sessão")

# Register documentation models
models = auth_contract.register_models(api)

login_request_schema = LoginRequestSchema()
token_response_schema = TokenResponseSchema()


@api.route("/login")
class AuthLogin(Resource):
    @api.doc(
        "auth_login",
        responses={
            200: "Login successful - returns JWT token",
            400: "Validation error",
            401: "Invalid credentials",
            429: "Too many login attempts - rate limited",
        },
    )
    @api.expect(models["login_request"])
    @api.response(200, "Success", models["token_response"])
    def post(self) -> tuple[dict[str, Any], int]:
        """
        Authenticate user and get JWT token.

        Use the returned token in the `Authorization` header for authenticated requests:
        `Authorization: Bearer <token>`
        """
        data = request.get_json(silent=True) or {}
        payload = login_request_schema.load(data)

        response = auth_service.login_user(payload)
        return token_response_schema.dump(response), 200


@api.route("/forgot-password")
class AuthForgotPassword(Resource):
    @api.doc(
        "auth_forgot_password",
        responses={
            200: "If request accepted (email sent if user exists)",
            400: "Invalid email format",
        },
    )
    @api.expect(models["forgot_password_request"])
    def post(self) -> tuple[dict[str, Any], int]:
        """Request password recovery. Sends email with reset link if the user exists."""
        data = request.get_json() or {}
        email = (data.get("email") or "").strip()
        if not email:
            raise ValidationError("E-mail é obrigatório")
        # URL pública configurada: request.url_root vira http:// atrás do nginx sem ProxyFix.
        base_url = (current_app.config.get("FRONTEND_URL") or request.url_root).rstrip("/")
        auth_service.request_password_reset(email, base_url)
        return {
            "message": "Se o e-mail estiver cadastrado, você receberá um link para redefinir a senha."
        }, 200


@api.route("/reset-password")
class AuthResetPassword(Resource):
    @api.doc(
        "auth_reset_password",
        responses={
            200: "Senha redefinida",
            400: "Token inválido ou expirado, senhas diferentes ou senha fraca",
        },
    )
    @api.expect(models["reset_password_request"])
    def post(self) -> tuple[dict[str, Any], int]:
        """Redefine a senha com o token recebido por e-mail (tela do app em /redefinir-senha)."""
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        new_password = (data.get("new_password") or "").strip()
        confirm = (data.get("confirm_password") or "").strip()
        if not token:
            raise ValidationError("Token é obrigatório")
        if not new_password:
            raise ValidationError("Nova senha é obrigatória")
        if new_password != confirm:
            raise ValidationError("As senhas não coincidem")
        auth_service.reset_password(token, new_password)
        return {"message": "Senha redefinida com sucesso. Faça login com a nova senha."}, 200

