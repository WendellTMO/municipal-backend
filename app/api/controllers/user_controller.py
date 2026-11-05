from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import aluno_contract, user_contract
from app.api.helpers import list_envelope
from app.schemas.aluno_schema import AlunoProvisionAccountRequestSchema
from app.schemas.user_schema import (
    ChangePasswordRequestSchema,
    ChangePasswordResponseSchema,
    FcmTokenRequestSchema,
    FcmTokenResponseSchema,
    MotoristaCreateRequestSchema,
    UpdateProfileRequestSchema,
    UserListResponseSchema,
    UserResponseSchema,
)
from app.services import user_service

api = Namespace("users", description="Gerenciamento de Usuários e Perfil")

# API contracts (Swagger documentation)
models = user_contract.register_models(api)
models_aluno = aluno_contract.register_models(api)

# Validation schemas (Marshmallow)
user_list_response_schema = UserListResponseSchema()
motorista_create_schema = MotoristaCreateRequestSchema()
change_password_schema = ChangePasswordRequestSchema()
aluno_provision_account_request_schema = AlunoProvisionAccountRequestSchema()
user_response_schema = UserResponseSchema()
change_password_response_schema = ChangePasswordResponseSchema()
fcm_token_request_schema = FcmTokenRequestSchema()
fcm_token_response_schema = FcmTokenResponseSchema()
update_profile_schema = UpdateProfileRequestSchema()


@api.route("")
class UserList(Resource):
    @api.doc("list_users", responses={200: "Success", 403: "Forbidden - not a gestor"})
    @api.response(200, "Success", models["user_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        """Lista todos os usuários da prefeitura (Apenas Gestor)"""
        current_user_id = get_jwt_identity()
        users = user_service.get_all_users(current_user_id)
        return (
            user_list_response_schema.dump(list_envelope(users)),
            200,
        )


@api.route("/me")
class UserProfile(Resource):
    @api.doc("get_my_profile", responses={200: "Success", 404: "User not found"})
    @api.response(200, "Success", models["user_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        """Perfil do usuário logado"""
        current_user_id = get_jwt_identity()
        user = user_service.get_user_by_id(current_user_id)
        return user_response_schema.dump(user), 200

    @api.doc(
        "update_my_profile",
        responses={200: "Updated", 400: "Validation error", 409: "Conflict"},
    )
    @api.expect(models["update_profile_request"])
    @api.response(200, "Success", models["user_response"])
    @jwt_required()
    def patch(self) -> tuple[dict[str, Any], int]:
        """Atualiza perfil do usuário logado (nome, telefone, receber_notificacoes, cnh)"""
        current_user_id = get_jwt_identity()
        payload = update_profile_schema.load(request.get_json(silent=True) or {})
        user = user_service.update_profile(current_user_id, payload)
        return user_response_schema.dump(user), 200


@api.route("/<string:id>")
@api.param("id", "O UUID do usuário")
class UserResource(Resource):
    @api.doc("get_user_by_id", responses={200: "Success", 403: "Forbidden", 404: "User not found"})
    @api.response(200, "Success", models["user_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        """Busca usuário por ID (próprio perfil ou mesma prefeitura se Gestor)"""
        current_user_id = get_jwt_identity()
        user = user_service.get_user_by_id(id, current_user_id)
        return user_response_schema.dump(user), 200


@api.route("/alunos")
class AlunoProvisionAccountResource(Resource):
    @api.doc(
        "aluno_provision_account",
        responses={
            201: "Aluno account created",
            400: "Validation error",
            403: "Forbidden - not a gestor",
            409: "Conflict - duplicate email/CPF",
        },
    )
    @api.expect(models_aluno["aluno_provision_account_request"])
    @jwt_required()
    def post(self):
        """Gestor provisiona uma nova conta de aluno"""
        current_user_id = get_jwt_identity()
        data = request.get_json() or {}
        payload = aluno_provision_account_request_schema.load(data)

        aluno = user_service.create_aluno_account(current_user_id, payload)
        return {"message": "Aluno account created with success", "id": str(aluno.id)}, 201


@api.route("/motoristas/<string:motorista_id>")
class MotoristaResource(Resource):
    @api.doc(
        "delete_motorista",
        responses={200: "Deleted", 403: "Forbidden", 404: "Not found", 400: "Has linked trips"},
    )
    @jwt_required()
    def delete(self, motorista_id: str) -> tuple[dict[str, Any], int]:
        """Gestor remove um motorista"""
        current_user_id = get_jwt_identity()
        user_service.delete_motorista(current_user_id, motorista_id)
        return {"message": "Motorista removido com sucesso"}, 200


@api.route("/motoristas")
class MotoristaCreateResource(Resource):
    @api.doc("list_motoristas", responses={200: "Success", 403: "Forbidden - not a gestor"})
    @api.marshal_list_with(models["user_list_response"], code=200)
    @jwt_required()
    def get(self) -> tuple[list[dict[str, Any]], int]:
        """Lista motoristas do mesmo município do Gestor"""
        current_user_id = get_jwt_identity()
        motoristas = user_service.get_motoristas_by_municipio(current_user_id)
        return (
            user_list_response_schema.dump(list_envelope(motoristas)),
            200,
        )

    @api.doc(
        "create_motorista",
        responses={
            201: "Motorista created",
            400: "Validation error",
            403: "Forbidden - not a gestor",
            409: "Conflict",
        },
    )
    @api.expect(models["motorista_create_request"])
    @api.response(201, "Motorista created", models["user_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Gestor cria um novo Motorista"""
        current_user_id = get_jwt_identity()
        payload = motorista_create_schema.load(request.get_json(silent=True) or {})

        motorista = user_service.create_motorista(current_user_id, payload)
        return user_response_schema.dump(motorista), 201


@api.route("/change-password")
class UserChangePassword(Resource):
    @api.doc(
        "change_user_password",
        responses={
            200: "Password changed successfully",
            400: "Validation error",
            429: "Troca travada por 15 minutos depois de 5 erros da senha atual",
        },
    )
    @api.expect(models["change_password_request"])
    @api.response(200, "Password changed successfully", models["change_password_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Altera a senha do usuário logado (Requer senha atual)."""
        current_user_id = get_jwt_identity()
        payload = change_password_schema.load(request.get_json(silent=True) or {})

        resposta = user_service.change_password(current_user_id, payload)
        return change_password_response_schema.dump(resposta), 200


@api.route("/fcm-token")
class UserFcmToken(Resource):
    @api.doc("update_fcm_token", responses={200: "Token atualizado", 400: "Token não enviado"})
    @api.expect(models["fcm_token_request"])
    @api.response(200, "Token updated successfully")
    @jwt_required()
    def patch(self) -> tuple[dict[str, str], int]:
        """Atualiza o Token do Firebase (Push Notifications) do aparelho do usuário"""
        current_user_id = get_jwt_identity()
        data = request.get_json() or {}
        payload = fcm_token_request_schema.load(data)

        user_service.update_fcm_token(current_user_id, payload)
        return (
            fcm_token_response_schema.dump(
                {"message": "Token de notificação atualizado com sucesso"}
            ),
            200,
        )
