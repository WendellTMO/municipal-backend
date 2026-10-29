from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import ponto_contract, viagem_contract
from app.api.contracts.viagem_parsers import parsers
from app.api.helpers import list_envelope
from app.core.exceptions import ValidationError
from app.schemas.ponto_schema import (
    PontoFlatListResponseSchema,
)
from app.schemas.viagem_schema import (
    MessageResponseSchema,
    ViagemAcaoRequestSchema,
    ViagemAgendaAlunoListResponseSchema,
    ViagemAlunoConfirmacaoResponseSchema,
    ViagemConfirmacaoRequestSchema,
    ViagemCreateRequestSchema,
    ViagemListQuerySchema,
    ViagemListResponseSchema,
    ViagemLoteRequestSchema,
    ViagemLoteResponseSchema,
    ViagemPontoCreateRequestSchema,
    ViagemResponseSchema,
)
from app.services import viagens_service

api = Namespace("viagens", description="Execução de Viagens")

ponto_models = ponto_contract.register_models(api)

# API contracts (Swagger documentation)
models = viagem_contract.register_models(api)

# Validation schemas (Marshmallow)
viagem_response_schema = ViagemResponseSchema()
viagem_list_response_schema = ViagemListResponseSchema()

viagem_create_request_schema = ViagemCreateRequestSchema()
viagem_lote_request_schema = ViagemLoteRequestSchema()
viagem_confirmacao_request_schema = ViagemConfirmacaoRequestSchema()
viagem_acao_request_schema = ViagemAcaoRequestSchema()
viagem_ponto_create_request_schema = ViagemPontoCreateRequestSchema()

viagem_list_query_schema = ViagemListQuerySchema()

message_response_schema = MessageResponseSchema()
viagem_lote_response_schema = ViagemLoteResponseSchema()
viagem_aluno_confirmacao_response_schema = ViagemAlunoConfirmacaoResponseSchema()
viagem_agenda_aluno_list_response_schema = ViagemAgendaAlunoListResponseSchema()


ponto_flat_list_response_schema = PontoFlatListResponseSchema()


@api.route("/aluno/agenda")
class AlunoAgendaResource(Resource):
    @api.doc("list_viagens_aluno")
    @api.response(200, "Success", models["viagem_agenda_aluno_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        agenda = viagens_service.get_proximas_viagens_aluno(user_id)
        return (
            viagem_agenda_aluno_list_response_schema.dump(list_envelope(agenda)),
            200,
        )


@api.route("/<string:id>/pontos-embarque")
class ViagemPontosResource(Resource):
    @api.doc("list_pontos_embarque_viagem")
    @api.response(200, "Success", ponto_models["ponto_flat_list_response"])
    @jwt_required()
    def get(self, id: str) -> tuple[dict[str, Any], int]:
        """Lista todos os pontos de embarque disponíveis para esta viagem."""
        user_id = get_jwt_identity()
        pontos = viagens_service.listar_pontos_embarque(user_id, id)
        return (
            ponto_flat_list_response_schema.dump(list_envelope(pontos)),
            200,
        )


@api.route("/<string:id>/confirmacao")
class ViagemConfirmacaoResource(Resource):
    @api.doc("confirmar_presenca")
    @api.expect(models["viagem_confirmacao_request"])
    @api.response(200, "Success", models["viagem_aluno_confirmacao_response"])
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = viagem_confirmacao_request_schema.load(data)
        result = viagens_service.confirmar_presenca_aluno(user_id, id, payload)
        return viagem_aluno_confirmacao_response_schema.dump(result), 200


@api.route("/")
class ViagemListResource(Resource):
    @api.doc("list_all_viagens")
    @api.expect(parsers["viagem_list"])
    @api.response(200, "Success", models["viagem_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        filters = viagem_list_query_schema.load(request.args.to_dict())
        viagens = viagens_service.list_viagens_gestor(user_id, filters)
        return (
            viagem_list_response_schema.dump(list_envelope(viagens)),
            200,
        )

    @api.doc("create_viagem")
    @api.expect(models["viagem_create_request"])
    @api.response(201, "Created", models["viagem_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = viagem_create_request_schema.load(data)
        result = viagens_service.gerar_viagem(user_id, payload)

        # gerar_viagem returns {message,id,dia}. If you want to return ViagemResponseSchema instead,
        # change service to return the Viagem ORM instance. For now, keep it consistent with existing behavior.
        return result, 201


@api.route("/gerar-lote")
class ViagemLoteResource(Resource):
    @api.doc("gerar_viagens_lote")
    @api.expect(models["viagem_lote_request"])
    @api.response(201, "Created", models["viagem_lote_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = viagem_lote_request_schema.load(data)
        result = viagens_service.gerar_viagens_em_lote(user_id, payload["data"])
        return viagem_lote_response_schema.dump(result), 201


@api.route("/minhas")
class MinhasViagensResource(Resource):
    @api.doc("list_my_viagens")
    @api.response(200, "Success", models["viagem_list_response"])
    @jwt_required()
    def get(self) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        viagens = viagens_service.list_viagens_motorista(user_id)
        return (
            viagem_list_response_schema.dump(list_envelope(viagens)),
            200,
        )


@api.route("/<string:id>/acao")
class ViagemAcaoResource(Resource):
    @api.doc("control_viagem")
    @api.expect(models["viagem_acao_request"])
    @api.response(200, "Success", models["viagem_response"])
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = viagem_acao_request_schema.load(data)
        viagem = viagens_service.controlar_viagem(user_id, id, payload)
        return viagem_response_schema.dump(viagem), 200


@api.route("/<string:id>/pontos")
class ViagemPontoNaHoraResource(Resource):
    @api.doc("adicionar_ponto_na_viagem")
    @api.expect(models["viagem_ponto_create_request"])
    @api.response(201, "Created", models["viagem_response"])
    @jwt_required()
    def post(self, id: str) -> tuple[dict[str, Any], int]:
        """(Motorista) Adiciona um ponto só a esta viagem em andamento."""
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = viagem_ponto_create_request_schema.load(data)
        viagem = viagens_service.adicionar_ponto_na_viagem(user_id, id, payload)
        return viagem_response_schema.dump(viagem), 201


@api.route("/<string:id>/cancelar")
class ViagemCancelarResource(Resource):
    @api.doc("cancelar_viagem")
    @api.response(200, "Trip cancelled successfully")
    @jwt_required()
    def put(self, id: str) -> tuple[dict[str, Any], int]:
        """Cancela uma viagem agendada e notifica alunos (Gestor)"""
        user_id = get_jwt_identity()
        result = viagens_service.cancelar_viagem(user_id, id)
        return result, 200


@api.route("/<string:id>/localizacao")
class ViagemLocalizacaoResource(Resource):
    @api.doc("atualizar_localizacao_onibus")
    @api.expect(models["localizacao_request"])
    @jwt_required()
    def post(self, id):
        """(Motorista) Envia coordenada GPS atual do ônibus em tempo real"""
        user_id = get_jwt_identity()
        data = request.get_json()

        result = viagens_service.atualizar_localizacao(user_id, id, data)
        return result, 200

    @api.doc("obter_localizacao_onibus")
    @jwt_required()
    def get(self, id):
        """(Aluno/Motorista) Obtém a localização atual do ônibus (viagem em andamento)."""
        user_id = get_jwt_identity()
        result = viagens_service.obter_localizacao_onibus(user_id, id)
        return result, 200


@api.route("/<uuid:viagem_id>/localizacao-aluno")
class ViagemLocalizacaoAluno(Resource):
    """Endpoint for students to broadcast their real-time location during an active trip."""

    @api.doc("atualizar_localizacao_aluno", security="Bearer Auth")
    @api.expect(models["localizacao_request"])
    @jwt_required()
    def post(self, viagem_id: str):
        """Recebe o GPS em tempo real do Aluno para o Auto-Checkin (Geofencing)."""
        current_user_id = get_jwt_identity()

        data = request.get_json() or {}

        if "latitude" not in data or "longitude" not in data:
            raise ValidationError("Latitude e longitude são obrigatórias na requisição.")

        resultado = viagens_service.atualizar_localizacao_aluno(
            user_id=current_user_id, viagem_id=str(viagem_id), data=data
        )

        return resultado, 200
