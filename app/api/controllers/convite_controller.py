from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import convite_contract
from app.api.helpers import list_envelope
from app.schemas.convite_schema import (
    ConviteAceiteRequestSchema,
    ConviteListQuerySchema,
    ConviteListResponseSchema,
    ConviteLoteRequestSchema,
    ConviteResponseSchema,
    ConviteValidarPinRequestSchema,
)
from app.services import convite_service

api = Namespace("convites", description="Convites para o aluno concluir o cadastro")

models = convite_contract.register_models(api)

lote_request_schema = ConviteLoteRequestSchema()
list_query_schema = ConviteListQuerySchema()
convite_response_schema = ConviteResponseSchema()
list_response_schema = ConviteListResponseSchema()
validar_pin_request_schema = ConviteValidarPinRequestSchema()
aceite_request_schema = ConviteAceiteRequestSchema()


@api.route("/")
class ConviteListResource(Resource):
    @api.doc("create_convites")
    @api.expect(models["convite_lote_request"])
    @api.response(201, "Resultado por linha", models["convite_lote_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Pré-cadastra alunos em lote (até 500). Os e-mails saem pelo job de envio."""
        payload = lote_request_schema.load(request.get_json(silent=True) or {})
        resultados = convite_service.criar_convites(get_jwt_identity(), payload["convites"])
        return list_envelope(resultados), 201

    @api.doc("list_convites")
    @api.response(200, "Success", models["convite_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        filtros = list_query_schema.load(request.args.to_dict())
        convites = convite_service.listar_convites(get_jwt_identity(), filtros["status"])
        return list_response_schema.dump(list_envelope(convites)), 200


@api.route("/<string:id>/reenviar")
class ConviteReenviarResource(Resource):
    @api.doc("reenviar_convite")
    @api.response(200, "Success")
    @jwt_required()
    def post(self, id: str) -> tuple[dict[str, Any], int]:
        """Volta o convite para a fila: link e PIN novos, os anteriores deixam de valer."""
        convite = convite_service.reenviar_convite(get_jwt_identity(), id)
        return convite_response_schema.dump(convite), 200


@api.route("/<string:id>")
class ConviteResource(Resource):
    @api.doc("cancelar_convite")
    @api.response(200, "Success")
    @jwt_required()
    def delete(self, id: str) -> tuple[dict[str, Any], int]:
        convite_service.cancelar_convite(get_jwt_identity(), id)
        return {"message": "Convite cancelado com sucesso"}, 200


@api.route("/aceite/<string:token>/validar")
class ConviteValidarPinResource(Resource):
    @api.doc("validar_pin_convite")
    @api.expect(models["validar_pin_request"])
    def post(self, token: str) -> tuple[dict[str, Any], int]:
        """Público. Com o PIN correto, devolve os dados do convite e os termos de uso."""
        payload = validar_pin_request_schema.load(request.get_json(silent=True) or {})
        return convite_service.validar_pin(token, payload["pin"]), 200


@api.route("/aceite/<string:token>")
class ConviteAceiteResource(Resource):
    @api.doc("aceitar_convite")
    @api.expect(models["aceite_request"])
    def post(self, token: str) -> tuple[dict[str, Any], int]:
        """Público. Cria a conta do aluno a partir do convite."""
        payload = aceite_request_schema.load(request.get_json(silent=True) or {})
        aluno = convite_service.aceitar_convite(token, payload)
        resposta = {
            "id": str(aluno.id),
            "email": aluno.email,
            "status": aluno.status.value,
            "requer_consentimento_responsavel": aluno.is_minor,
        }
        return resposta, 201
