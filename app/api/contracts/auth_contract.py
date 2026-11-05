"""Auth endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    """Register auth models with the API namespace."""

    login_request = api.model(
        "LoginRequest",
        {
            "email": fields.String(required=True, description="Email do usuário"),
            "password": fields.String(required=True, description="Senha"),
        },
    )

    user_info = api.model(
        "UserInfo",
        {
            "id": fields.String(description="ID do usuário"),
            "nome": fields.String(description="Nome do usuário"),
            "email": fields.String(description="Email do usuário"),
            "role": fields.String(description="Perfil do usuário"),
        },
    )

    token_response = api.model(
        "TokenResponse",
        {
            "message": fields.String(description="Mensagem de sucesso"),
            "token": fields.String(description="JWT Token"),
            "user": fields.Nested(user_info, description="Dados do usuário"),
        },
    )

    forgot_password_request = api.model(
        "ForgotPasswordRequest",
        {"email": fields.String(required=True, description="Email para recuperação de senha")},
    )

    reset_password_request = api.model(
        "ResetPasswordRequest",
        {
            "token": fields.String(required=True, description="Token do link recebido por e-mail"),
            "new_password": fields.String(required=True, description="Nova senha (mínimo 8)"),
            "confirm_password": fields.String(required=True, description="Repetição da nova senha"),
        },
    )

    change_password_request = api.model(
        "ChangePasswordRequest",
        {
            "current_password": fields.String(required=True, description="Senha atual"),
            "new_password": fields.String(required=True, description="Nova senha (8 a 128)"),
            "confirm_password": fields.String(required=True, description="Repetição da nova senha"),
        },
    )

    return {
        "change_password_request": change_password_request,
        "login_request": login_request,
        "token_response": token_response,
        "forgot_password_request": forgot_password_request,
        "reset_password_request": reset_password_request,
    }
