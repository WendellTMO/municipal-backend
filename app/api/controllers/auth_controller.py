from html import escape
from typing import Any

from flask import Response, current_app, request
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


def _reset_password_form_html(token: str, action_url: str) -> str:
    """Minimal HTML form for password reset (used when user opens the link in browser)."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Redefinir senha - BusKá</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 360px; margin: 48px auto; padding: 24px; }}
  input {{ width: 100%; padding: 10px; margin: 8px 0; box-sizing: border-box; }}
  button {{ width: 100%; padding: 12px; margin-top: 8px; background: #0F2942; color: #fff; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; }}
  .msg {{ font-size: 0.9rem; color: #333; margin-bottom: 16px; }}
  .error {{ color: #c62828; font-size: 0.9rem; }}
</style>
</head>
<body>
  <h1>Redefinir senha</h1>
  <p class="msg">Digite sua nova senha (mínimo 8 caracteres).</p>
  <form method="POST" action="{escape(action_url)}">
    <input type="hidden" name="token" value="{escape(token)}">
    <input type="password" name="new_password" placeholder="Nova senha" required minlength="8" autocomplete="new-password">
    <input type="password" name="confirm_password" placeholder="Confirmar senha" required minlength="8" autocomplete="new-password">
    <button type="submit">Redefinir senha</button>
  </form>
</body>
</html>"""


@api.route("/reset-password")
@api.doc(False)
class AuthResetPassword(Resource):
    def get(self) -> Response:
        """Serve HTML form to reset password (link in email)."""
        token = request.args.get("token", "").strip()
        if not token:
            html = "<!DOCTYPE html><html><body><p>Link inválido: token ausente.</p></body></html>"
            return Response(html, status=400, mimetype="text/html; charset=utf-8")
        action_url = request.path
        html = _reset_password_form_html(token, action_url)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    def post(self) -> tuple[dict[str, Any], int]:
        """Reset password with token (from form or API)."""
        data = request.get_json(silent=True) or request.form
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
