from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import telemetria_contract
from app.core.exceptions import ValidationError
from app.services import telemetria_service

api = Namespace("telemetria", description="Eventos de uso do app, sem dado pessoal")

models = telemetria_contract.register_models(api)


@api.route("")
class TelemetriaResource(Resource):
    @api.doc(
        "enviar_telemetria",
        responses={200: "Lote recebido", 400: "Lote inválido", 401: "Unauthorized"},
    )
    @api.expect(models["telemetria_lote"])
    @api.response(200, "Lote recebido", models["telemetria_resposta"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Recebe um lote de até 50 eventos de uso do usuário logado."""
        dados = request.get_json(silent=True)
        if not isinstance(dados, dict):
            raise ValidationError("Corpo inválido")
        contexto = dados.get("contexto")
        eventos = dados.get("eventos")
        if not isinstance(contexto, dict) or not isinstance(eventos, list):
            raise ValidationError("contexto e eventos são obrigatórios")
        return telemetria_service.registrar_lote(get_jwt_identity(), contexto, eventos), 200
