from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import instituicao_contract
from app.api.contracts.instituicao_parsers import parsers
from app.api.helpers import list_envelope
from app.schemas.instituicao_schema import (
    InstituicaoBuscaQuerySchema,
    InstituicaoBuscaResponseSchema,
    InstituicaoCreateRequestSchema,
    InstituicaoListQuerySchema,
    InstituicaoListResponseSchema,
    InstituicaoResponseSchema,
)
from app.services import instituicao_service

api = Namespace("instituicoes", description="Gestão de Escolas e Instituições de Ensino")

# API contracts (Swagger documentation)
models = instituicao_contract.register_models(api)

# Validation schemas (Marshmallow)
instituicao_create_request_schema = InstituicaoCreateRequestSchema()
instituicao_response_schema = InstituicaoResponseSchema()
instituicao_list_response_schema = InstituicaoListResponseSchema()
instituicao_list_query_schema = InstituicaoListQuerySchema()
instituicao_busca_query_schema = InstituicaoBuscaQuerySchema()
instituicao_busca_response_schema = InstituicaoBuscaResponseSchema()


@api.route("/public")
class InstituicaoPublicListResource(Resource):
    @api.doc("list_instituicoes_public")
    @api.expect(parsers["instituicao_list"])
    @api.response(200, "Success", models["instituicao_list_response"])
    def get(self) -> tuple[dict[str, Any], int]:
        filters = instituicao_list_query_schema.load(request.args.to_dict())
        instituicoes = instituicao_service.list_all_public(filters)

        return (
            instituicao_list_response_schema.dump(list_envelope(instituicoes)),
            200,
        )


@api.route("/busca")
class InstituicaoBuscaResource(Resource):
    @api.doc("buscar_instituicoes")
    @api.expect(parsers["instituicao_busca"])
    @api.response(200, "Success", models["instituicao_busca_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        """Busca instituições da prefeitura do usuário, melhores resultados primeiro."""
        user_id = get_jwt_identity()
        filtros = instituicao_busca_query_schema.load(request.args.to_dict())
        itens = instituicao_service.buscar(user_id, filtros["q"], filtros["limit"])
        return instituicao_busca_response_schema.dump(list_envelope(itens)), 200


@api.route("/")
class InstituicaoListResource(Resource):
    @api.doc("list_instituicoes")
    @api.response(200, "Success", models["instituicao_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        instituicoes = instituicao_service.list_all(user_id)
        return (
            instituicao_list_response_schema.dump(list_envelope(instituicoes)),
            200,
        )

    @api.doc("create_instituicao")
    @api.expect(models["instituicao_create_request"])
    @api.response(201, "Created", models["instituicao_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Cadastra uma nova instituição com endereço."""
        user_id = get_jwt_identity()
        payload = instituicao_create_request_schema.load(request.get_json(silent=True) or {})

        inst = instituicao_service.create_instituicao(user_id, payload)
        return instituicao_response_schema.dump(inst), 201


@api.route("/<string:id>")
class InstituicaoResource(Resource):
    @api.doc("get_instituicao")
    @api.response(200, "Success", models["instituicao_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        instituicao = instituicao_service.get_by_id(user_id, id)
        return instituicao_response_schema.dump(instituicao), 200

    @api.doc("delete_instituicao")
    @api.response(200, "Success")
    @jwt_required()
    def delete(self, id: str) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        instituicao_service.delete_instituicao(user_id, id)
        return {"message": "Instituição removida com sucesso"}, 200
