from html import escape
from typing import Any

from flask import Response, current_app, request
from flask_restx import Namespace, Resource

from app.api.contracts import auth_contract
from app.core.exceptions import AppError, ValidationError
from app.schemas.auth_schema import LoginRequestSchema, TokenResponseSchema
from app.services import auth_service
from app.utils.email_template import AMARELO_CLARO, COR_AZUL

FONTE_SISTEMA = "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"

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


def _pagina_marca(titulo: str, corpo: str) -> str:
    """Página HTML com a marca do BusKá (cabeçalho azul, cartão branco, rodapé)."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titulo)} - BusKá</title>
<style>
  body {{ margin: 0; background: #F2F5FA; color: #1F2937; font-family: {FONTE_SISTEMA}; }}
  header {{ background: {COR_AZUL}; padding: 22px 16px; text-align: center; }}
  .marca {{ font-size: 2rem; font-weight: 800; color: #fff; }}
  .marca span {{ color: {AMARELO_CLARO}; }}
  main {{ max-width: 420px; margin: -12px auto 0; padding: 0 16px; }}
  .cartao {{ background: #fff; border-radius: 16px; padding: 28px 22px; margin-top: 32px;
    box-shadow: 0 4px 16px rgba(3, 71, 208, 0.12); }}
  h1 {{ margin: 0 0 8px; font-size: 1.4rem; }}
  p {{ margin: 0 0 16px; line-height: 1.5; color: #4B5563; }}
  input {{ width: 100%; padding: 16px; margin: 6px 0; box-sizing: border-box; font-size: 1rem;
    border: 1px solid #CBD5E1; border-radius: 12px; }}
  .botao {{ display: block; width: 100%; padding: 16px; margin-top: 12px; box-sizing: border-box;
    background: {COR_AZUL}; color: #fff; border: none; border-radius: 12px; font-size: 1rem;
    font-weight: 700; text-align: center; text-decoration: none; cursor: pointer; }}
  footer {{ text-align: center; padding: 24px 16px; font-size: 0.85rem; color: #6B7280; }}
</style>
</head>
<body>
  <header><div class="marca"><span>Bus</span>Ká</div></header>
  <main><div class="cartao">{corpo}</div></main>
  <footer>gestão inteligente do transporte escolar municipal</footer>
</body>
</html>"""


def _reset_password_form_html(token: str, action_url: str) -> str:
    """Formulário de redefinição de senha (usado quando o link do e-mail abre no navegador)."""
    corpo = f"""<h1>Redefinir senha</h1>
  <p>Digite sua nova senha (mínimo 8 caracteres).</p>
  <form method="POST" action="{escape(action_url)}">
    <input type="hidden" name="token" value="{escape(token)}">
    <input type="password" name="new_password" placeholder="Nova senha" required minlength="8" autocomplete="new-password">
    <input type="password" name="confirm_password" placeholder="Confirmar senha" required minlength="8" autocomplete="new-password">
    <button class="botao" type="submit">Redefinir senha</button>
  </form>"""
    return _pagina_marca("Redefinir senha", corpo)


def _reset_password_sucesso_html(frontend_url: str) -> str:
    corpo = f"""<h1>Senha redefinida</h1>
  <p>Agora você já pode entrar no app.</p>
  <a class="botao" href="{escape(frontend_url)}">Entrar no app</a>"""
    return _pagina_marca("Senha redefinida", corpo)


def _reset_password_erro_html(mensagem: str) -> str:
    corpo = f"""<h1>Não foi possível redefinir</h1>
  <p>{escape(mensagem)}</p>
  <p>Solicite um novo link de recuperação de senha pelo app.</p>"""
    return _pagina_marca("Erro ao redefinir senha", corpo)


def _quer_json() -> bool:
    return request.is_json or "application/json" in request.headers.get("Accept", "")


def _html(html: str, status: int) -> Response:
    return Response(html, status=status, mimetype="text/html; charset=utf-8")


@api.route("/reset-password")
@api.doc(False)
class AuthResetPassword(Resource):
    def get(self) -> Response:
        """Serve HTML form to reset password (link in email)."""
        token = request.args.get("token", "").strip()
        if not token:
            return _html(_reset_password_erro_html("Link inválido: token ausente."), 400)
        return _html(_reset_password_form_html(token, request.path), 200)

    def post(self) -> Any:
        """Reset password with token (from form or API)."""
        if _quer_json():
            return self._redefinir_json()
        try:
            self._redefinir()
        except AppError as exc:
            return _html(_reset_password_erro_html(exc.message), exc.status_code)
        frontend_url = current_app.config.get("FRONTEND_URL") or "/"
        return _html(_reset_password_sucesso_html(frontend_url), 200)

    def _redefinir_json(self) -> tuple[dict[str, Any], int]:
        self._redefinir()
        return {"message": "Senha redefinida com sucesso. Faça login com a nova senha."}, 200

    def _redefinir(self) -> None:
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
