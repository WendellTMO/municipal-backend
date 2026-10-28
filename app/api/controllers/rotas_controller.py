from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import ponto_contract, rota_contract
from app.api.helpers import list_envelope
from app.schemas.horario_schema import (
    HorarioCreateRequestSchema,
    HorarioListResponseSchema,
    HorarioResponseSchema,
)
from app.schemas.ponto_schema import (
    PontoFlatListResponseSchema,
)
from app.schemas.rota_schema import (
    InstituicaoOrdemListResponseSchema,
    MeuPontoEmbarqueRequestSchema,
    RotaCreateRequestSchema,
    RotaDetailResponseSchema,
    RotaInscricaoRequestSchema,
    RotaInstituicoesOrdemRequestSchema,
    RotaListResponseSchema,
    RotaPontosAddRequestSchema,
    RotaResponseSchema,
    RotaUpdateRequestSchema,
)
from app.services import rotas_service

api = Namespace("rotas", description="Gestão de Rotas")

# API contracts (Swagger documentation)
models = rota_contract.register_models(api)
ponto_models = ponto_contract.register_models(api)

# Validation schemas (Marshmallow)
rota_response_schema = RotaResponseSchema()
rota_list_response_schema = RotaListResponseSchema()
rota_detail_response_schema = RotaDetailResponseSchema()

rota_create_request_schema = RotaCreateRequestSchema()
rota_update_request_schema = RotaUpdateRequestSchema()
inscricao_request_schema = RotaInscricaoRequestSchema()
pontos_add_request_schema = RotaPontosAddRequestSchema()
meu_ponto_request_schema = MeuPontoEmbarqueRequestSchema()

horario_create_request_schema = HorarioCreateRequestSchema()
horario_response_schema = HorarioResponseSchema()
horario_list_response_schema = HorarioListResponseSchema()

ponto_flat_list_response_schema = PontoFlatListResponseSchema()

ordem_request_schema = RotaInstituicoesOrdemRequestSchema()
ordem_response_schema = InstituicaoOrdemListResponseSchema()


@api.route("/")
class RotasListResource(Resource):
    @api.doc("list_rotas")
    @api.response(200, "Success", models["rota_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        rotas = rotas_service.list_all_rotas(current_user_id)
        return (
            rota_list_response_schema.dump(list_envelope(rotas)),
            200,
        )

    @api.doc("create_rota")
    @api.expect(models["rota_create_request"])
    @api.response(201, "Created", models["rota_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = rota_create_request_schema.load(data)

        rota = rotas_service.create_rota(current_user_id, payload)
        return rota_response_schema.dump(rota), 201


@api.route("/me")
class MyRotasResource(Resource):
    @api.doc("list_my_rotas")
    @api.response(200, "Success", models["rota_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        rotas = rotas_service.list_my_rotas(current_user_id)
        return (
            rota_list_response_schema.dump(list_envelope(rotas)),
            200,
        )


@api.route("/<string:id>/inscricao")
@api.param("id", "UUID da Rota")
class RotaInscricaoResource(Resource):
    @api.doc("inscrever_aluno")
    @api.expect(models["rota_inscricao_request"])
    @api.response(200, "Success")
    @jwt_required()
    def post(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = inscricao_request_schema.load(data)

        result = rotas_service.gerenciar_inscricao_aluno(current_user_id, id, payload)
        return result, 200


@api.route("/<string:id>/pontos")
class RotaPontosResource(Resource):
    @api.doc("list_rota_pontos")
    @api.response(200, "Success", ponto_models["ponto_flat_list_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        pontos = rotas_service.get_pontos_by_rota(current_user_id, id)
        return (
            ponto_flat_list_response_schema.dump(list_envelope(pontos)),
            200,
        )

    @api.doc("add_rota_pontos")
    @api.expect(models["rota_pontos_add_request"])
    @api.response(200, "Success")
    @jwt_required()
    def post(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = pontos_add_request_schema.load(data)

        rotas_service.add_ponto(current_user_id, id, payload)
        return {"message": "Pontos adicionados com sucesso"}, 200


@api.route("/<string:id>/meu-ponto-embarque")
class RotaMeuPontoEmbarqueResource(Resource):
    @api.doc("get_meu_ponto_embarque")
    @api.response(200, "Success", models["rota_meu_ponto_embarque_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        return rotas_service.get_meu_ponto_embarque(get_jwt_identity(), id), 200

    @api.doc("set_meu_ponto_embarque")
    @api.expect(models["rota_meu_ponto_embarque_request"])
    @api.response(200, "Success", models["rota_meu_ponto_embarque_response"])
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        data = request.get_json(silent=True) or {}
        payload = meu_ponto_request_schema.load(data)
        return rotas_service.set_meu_ponto_embarque(get_jwt_identity(), id, payload), 200


@api.route("/<string:id>/instituicoes/ordem")
class RotaInstituicoesOrdemResource(Resource):
    @api.doc("get_rota_instituicoes_ordem")
    @api.response(200, "Success", models["rota_instituicoes_ordem_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        itens = rotas_service.get_ordem_instituicoes(current_user_id, id)
        return ordem_response_schema.dump(list_envelope(itens)), 200

    @api.doc("set_rota_instituicoes_ordem")
    @api.expect(models["rota_instituicoes_ordem_request"])
    @api.response(200, "Success", models["rota_instituicoes_ordem_response"])
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = ordem_request_schema.load(data)
        itens = rotas_service.set_ordem_instituicoes(
            current_user_id, id, payload["instituicao_ids"]
        )
        return ordem_response_schema.dump(list_envelope(itens)), 200


@api.route("/<string:id>/horarios")
class RotaHorariosResource(Resource):
    @api.doc("list_rota_horarios")
    @api.response(200, "Success", models["rota_horario_list_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        current_user = get_jwt_identity()
        horarios = rotas_service.get_horarios(current_user, id)
        return (
            horario_list_response_schema.dump(list_envelope(horarios)),
            200,
        )

    @api.doc("add_rota_horario")
    @api.expect(models["rota_horario_create_request"])
    @api.response(201, "Created", models["rota_horario_response"])
    @jwt_required()
    def post(self, id: str) -> tuple[dict[str, Any], int]:
        current_user = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = horario_create_request_schema.load(data)

        horario = rotas_service.add_horario(current_user, id, payload)
        return horario_response_schema.dump(horario), 201


@api.route("/<string:id>")
class RotaResource(Resource):
    @api.doc("get_rota")
    @api.response(200, "Success", models["rota_detail_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        rota = rotas_service.get_by_id(current_user_id, id)
        return rota_detail_response_schema.dump(rota), 200

    @api.doc("update_rota")
    @api.expect(models["rota_update_request"])
    @api.response(200, "Success")
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = rota_update_request_schema.load(data)

        rota = rotas_service.update_rota(current_user_id, id, payload)
        return rota_response_schema.dump(rota), 200

    @api.doc("delete_rota")
    @api.response(200, "Success")
    @jwt_required()
    def delete(self, id: str) -> tuple[dict[str, Any], int]:
        current_user_id = get_jwt_identity()
        rotas_service.delete_rota(current_user_id, id)
        return {"message": "Rota removida com sucesso"}, 200
