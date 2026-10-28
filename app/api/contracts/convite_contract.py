"""Convite endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    convite_item = api.model(
        "ConviteItem",
        {
            "nome": fields.String(required=True, description="Nome do aluno"),
            "email": fields.String(required=True, description="E-mail do aluno"),
            "telefone": fields.String(description="Telefone com DDD"),
            "ponto_id": fields.String(description="Ponto da casa do aluno (UUID)"),
            "instituicao_id": fields.String(description="Instituição (UUID)"),
            "rota_id": fields.String(description="Rota em que o aluno será inscrito (UUID)"),
        },
    )
    convite_lote_request = api.model(
        "ConviteLoteRequest",
        {"convites": fields.List(fields.Nested(convite_item), required=True)},
    )
    convite_lote_linha = api.model(
        "ConviteLoteLinha",
        {
            "linha": fields.Integer(description="Posição da linha no lote, a partir de 1"),
            "email": fields.String(),
            "resultado": fields.String(description="CRIADO, RENOVADO, PULADO ou INVALIDO"),
            "motivo": fields.String(),
            "id": fields.String(description="UUID do convite, quando existe"),
        },
    )
    convite_lote_response = api.model(
        "ConviteLoteResponse", {"items": fields.List(fields.Nested(convite_lote_linha))}
    )
    convite_response = api.model(
        "ConviteResponse",
        {
            "id": fields.String(),
            "nome": fields.String(),
            "email": fields.String(),
            "telefone": fields.String(),
            "ponto_id": fields.String(),
            "instituicao_id": fields.String(),
            "rota_id": fields.String(),
            "status": fields.String(description="PENDENTE, ENVIADO, ACEITO, CANCELADO, EXPIRADO"),
            "expira_em": fields.DateTime(),
            "enviado_em": fields.DateTime(),
            "aceito_em": fields.DateTime(),
        },
    )
    convite_list_response = api.model(
        "ConviteListResponse",
        {
            "items": fields.List(fields.Nested(convite_response)),
            "total": fields.Integer(),
        },
    )
    validar_pin_request = api.model(
        "ConviteValidarPinRequest", {"pin": fields.String(required=True)}
    )
    aceite_request = api.model(
        "ConviteAceiteRequest",
        {
            "pin": fields.String(required=True),
            "senha": fields.String(required=True),
            "cpf": fields.String(required=True),
            "data_nascimento": fields.String(required=True, description="YYYY-MM-DD"),
            "aceite_termos": fields.Boolean(required=True),
            "telefone": fields.String(),
            "nome_responsavel": fields.String(description="Obrigatório para menor de 18 anos"),
            "cpf_responsavel": fields.String(),
            "email_responsavel": fields.String(description="Obrigatório para menor de 18 anos"),
        },
    )
    return {
        "convite_lote_request": convite_lote_request,
        "convite_lote_response": convite_lote_response,
        "convite_list_response": convite_list_response,
        "validar_pin_request": validar_pin_request,
        "aceite_request": aceite_request,
    }
