"""CEP endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    cep_response = api.model(
        "CepResponse",
        {
            "cep": fields.String(description="CEP só com dígitos", example="58429900"),
            "logradouro": fields.String(description="Rua (vazio se o CEP não tiver)"),
            "bairro": fields.String(description="Bairro (vazio se o CEP não tiver)"),
            "cidade": fields.String(description="Cidade"),
            "estado": fields.String(description="UF", example="PB"),
        },
    )
    return {"cep_response": cep_response}
