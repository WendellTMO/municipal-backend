from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from app.api.contracts import cep_contract
from app.services import cep_service

api = Namespace("cep", description="Consulta de CEP (pública)")

models = cep_contract.register_models(api)


def _ip_do_cliente() -> str:
    # Atrás do nginx o remote_addr é o do proxy; o último item do X-Forwarded-For
    # é o que o nosso nginx anexou.
    encaminhado = request.headers.get("X-Forwarded-For", "")
    if encaminhado:
        return encaminhado.split(",")[-1].strip()
    return request.remote_addr or "desconhecido"


@api.route("/<string:cep>")
class CepResource(Resource):
    @api.doc("consultar_cep")
    @api.response(200, "Success", models["cep_response"])
    @api.response(400, "CEP com formato inválido")
    @api.response(404, "CEP não encontrado")
    @api.response(429, "Limite de consultas por minuto excedido")
    @api.response(503, "Serviço de CEP indisponível")
    def get(self, cep: str) -> tuple[dict[str, Any], int]:
        """Consulta um CEP na ViaCEP (sem autenticação)"""
        return cep_service.consultar_cep(cep, _ip_do_cliente()), 200
