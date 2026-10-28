from marshmallow import fields, validate

from app.schemas.common import BaseSchema
from app.schemas.endereco_schema import EnderecoMoradiaInputSchema
from app.schemas.validators import validate_optional_cpf, validate_optional_phone


class ConviteLoteRequestSchema(BaseSchema):
    # Cada linha é validada no service, para uma linha ruim não derrubar o lote.
    convites = fields.List(
        fields.Dict(),
        required=True,
        validate=validate.Length(min=1, max=500, error="Envie de 1 a 500 convites por lote"),
    )


class ConviteListQuerySchema(BaseSchema):
    status = fields.String(load_default=None)


class ConviteResponseSchema(BaseSchema):
    id = fields.String()
    nome = fields.String()
    email = fields.String()
    telefone = fields.String(allow_none=True)
    instituicao_id = fields.String(allow_none=True)
    rota_id = fields.String(allow_none=True)
    status = fields.String()
    expira_em = fields.DateTime(allow_none=True)
    enviado_em = fields.DateTime(allow_none=True)
    aceito_em = fields.DateTime(allow_none=True)
    criado_por_id = fields.String(allow_none=True)
    aluno_id = fields.String(allow_none=True)
    created_at = fields.DateTime(allow_none=True)


class ConviteListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(ConviteResponseSchema))
    total = fields.Integer()


class ConviteValidarPinRequestSchema(BaseSchema):
    pin = fields.String(required=True, validate=validate.Length(min=1, max=20))


class ConviteAceiteRequestSchema(BaseSchema):
    pin = fields.String(required=True, validate=validate.Length(min=1, max=20))
    senha = fields.String(required=True, load_only=True, validate=validate.Length(min=1))
    cpf = fields.String(required=True, validate=validate.Length(min=1))
    data_nascimento = fields.Date(required=True, format="%Y-%m-%d")
    aceite_termos = fields.Boolean(required=True)
    endereco = fields.Nested(EnderecoMoradiaInputSchema, required=True)
    telefone = fields.String(load_default=None, allow_none=True, validate=validate_optional_phone)
    nome_responsavel = fields.String(load_default=None, allow_none=True)
    cpf_responsavel = fields.String(
        load_default=None, allow_none=True, validate=validate_optional_cpf
    )
    email_responsavel = fields.Email(load_default=None, allow_none=True)
