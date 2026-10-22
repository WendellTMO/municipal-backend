"""Ponto endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    """Register ponto models with the API namespace."""

    ponto_create_request = api.model(
        "PontoCreateRequest",
        {
            "apelido": fields.String(description="Nome do ponto (ex: Escola A)"),
            "latitude": fields.Float(required=True, description="Latitude"),
            "longitude": fields.Float(required=True, description="Longitude"),
        },
    )

    ponto_update_request = api.model(
        "PontoUpdateRequest",
        {
            "apelido": fields.String(description="Nome do ponto (ex: Escola A)"),
            "latitude": fields.Float(description="Latitude"),
            "longitude": fields.Float(description="Longitude"),
        },
    )

    ponto_response = api.model(
        "PontoResponse",
        {
            "id": fields.String(description="UUID do ponto"),
            "apelido": fields.String(description="Nome/apelido"),
            "latitude": fields.Float(description="Latitude"),
            "longitude": fields.Float(description="Longitude"),
            "endereco": fields.String(description="Endereço formatado"),
            "instituicao": fields.String(description="Instituição vinculada"),
        },
    )

    ponto_instituicao_response = api.model(
        "PontoInstituicaoResponse",
        {
            "id": fields.String(description="UUID da instituição"),
            "nome": fields.String(description="Nome da instituição"),
            "tipo": fields.String(description="Tipo (ex: Universidade Pública)"),
        },
    )

    ponto_flat_response = api.model(
        "PontoFlatResponse",
        {
            "id": fields.String(description="UUID do ponto"),
            "apelido": fields.String(description="Nome/apelido"),
            "latitude": fields.Float(description="Latitude"),
            "longitude": fields.Float(description="Longitude"),
            "ordem": fields.Integer(description="Ordem"),
            "instituicao": fields.Nested(
                ponto_instituicao_response,
                allow_null=True,
                description="Instituição de ensino no ponto (null quando não há)",
            ),
        },
    )

    ponto_flat_list_response = api.model(
        "PontoFlatListResponse",
        {
            "items": fields.List(fields.Nested(ponto_flat_response)),
            "total": fields.Integer(description="Total de pontos"),
        },
    )

    ponto_list_response = api.model(
        "PontoListResponse",
        {
            "items": fields.List(fields.Nested(ponto_response)),
            "total": fields.Integer(description="Total de pontos"),
        },
    )

    return {
        "ponto_create_request": ponto_create_request,
        "ponto_response": ponto_response,
        "ponto_flat_response": ponto_flat_response,
        "ponto_flat_list_response": ponto_flat_list_response,
        "ponto_list_response": ponto_list_response,
        "ponto_update_request": ponto_update_request,
    }
