from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import aluno_contract
from app.api.helpers import list_envelope
from app.schemas.aluno_schema import (
    AlunoGuardianConsentPublicSchema,
    AlunoListResponseSchema,
    AlunoMeUpdateRequestSchema,
    AlunoResponseSchema,
    AlunoSelfSignupRequestSchema,
)
from app.services import aluno_service

api = Namespace("alunos", description="Área do Aluno (App)")

# API contracts (Swagger documentation)
models = aluno_contract.register_models(api)

# Validation / serialisation schemas (Marshmallow)
self_signup_schema = AlunoSelfSignupRequestSchema()
me_update_schema = AlunoMeUpdateRequestSchema()
aluno_response_schema = AlunoResponseSchema()
aluno_list_response_schema = AlunoListResponseSchema()
guardian_public_schema = AlunoGuardianConsentPublicSchema()


@api.route("/signup")
class AlunoSignupResource(Resource):
    @api.doc("aluno_signup", security=[])
    @api.expect(models["self_signup_request"])
    @api.response(201, "Success", models["aluno_response"])
    def post(self):
        """Auto-cadastro do Aluno (Público)"""
        data = request.get_json(silent=True) or {}
        payload = self_signup_schema.load(data)
        aluno = aluno_service.auto_cadastro(payload)
        return aluno_response_schema.dump(aluno), 201


@api.route("/me")
class AlunoMeResource(Resource):
    @api.doc("aluno_get_profile")
    @api.response(200, "Success", models["aluno_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        """Aluno lê seu próprio perfil (inclui o endereço de moradia)"""
        aluno = aluno_service.get_me(get_jwt_identity())
        return aluno_response_schema.dump(aluno), 200

    @api.doc("aluno_profile")
    @api.expect(models["me_update_request"])
    @api.response(200, "Success", models["aluno_response"])
    @jwt_required()
    def put(self) -> tuple[dict[str, Any], int]:
        """Aluno atualiza seu perfil (Dados Pessoais + Endereço)"""
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = me_update_schema.load(data)

        aluno = aluno_service.update_me(user_id, payload)
        return aluno_response_schema.dump(aluno), 200

    @api.doc("aluno_delete")
    @api.response(200, "Success")
    @jwt_required()
    def delete(self) -> tuple[dict[str, Any], int]:
        """Aluno exclui sua conta"""
        user_id = get_jwt_identity()
        aluno_service.delete_me(user_id)
        return {"message": "Conta excluída com sucesso"}, 200


@api.route("/")
class AlunoListResource(Resource):
    @api.doc("list_alunos_gestor")
    @api.param("status", "Filter by status (PENDING_APPROVAL, ACTIVE, ...)", _in="query")
    @api.response(200, "Lista de alunos retornada com sucesso", models["aluno_list_response"])
    @api.response(400, "Parâmetros inválidos ou ausentes")
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        """Gestor vê lista de alunos cadastrados"""
        user_id = get_jwt_identity()
        status_filter = request.args.get("status")
        alunos = aluno_service.list_alunos_gestor(user_id, status=status_filter)
        return (
            aluno_list_response_schema.dump(list_envelope(alunos)),
            200,
        )


@api.route("/<string:aluno_id>")
class AlunoDetailResource(Resource):
    @api.doc("get_aluno_detail")
    @api.response(200, "Success", models["aluno_response"])
    @jwt_required()
    def get(self, aluno_id: str) -> tuple[dict[str, Any], int]:
        """(Gestor) Obtém detalhes completos de um aluno"""
        gestor_id = get_jwt_identity()
        aluno = aluno_service.get_aluno_by_id(gestor_id, aluno_id)
        return aluno_response_schema.dump(aluno), 200


@api.route("/<string:aluno_id>/aprovar")
class AlunoAprovarResource(Resource):
    @api.doc("aprovar_aluno")
    @api.response(200, "Success")
    @jwt_required()
    def post(self, aluno_id: str) -> tuple[dict[str, Any], int]:
        """(Gestor) Aprova cadastro de um aluno menor"""
        gestor_id = get_jwt_identity()
        aluno = aluno_service.aprovar_aluno(gestor_id, aluno_id)
        return aluno_response_schema.dump(aluno), 200


@api.route("/guardian-consent/<string:token>")
class GuardianConsentResource(Resource):
    @api.doc("guardian_consent_info", security=[])
    @api.response(200, "Success", models["guardian_consent_response"])
    def get(self, token: str) -> tuple[dict[str, Any], int]:
        """(Público) Busca dados do aluno para a tela de consentimento do responsável"""
        aluno = aluno_service.get_guardian_consent_info(token)
        return guardian_public_schema.dump(aluno), 200

    @api.doc("guardian_consent_confirm", security=[])
    @api.response(200, "Success", models["aluno_response"])
    def post(self, token: str) -> tuple[dict[str, Any], int]:
        """(Público) Responsável confirma consentimento para o aluno menor"""
        aluno = aluno_service.record_guardian_consent(token)
        return aluno_response_schema.dump(aluno), 200
