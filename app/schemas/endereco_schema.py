from marshmallow import fields, validate

from app.schemas.common import BaseSchema


class EnderecoInputSchema(BaseSchema):
    logradouro = fields.String(required=True)
    numero = fields.String(required=True)
    bairro = fields.String(required=True)
    cidade = fields.String(required=True)
    cep = fields.String(required=True)
    latitude = fields.Float(required=True)
    longitude = fields.Float(required=True)


class EnderecoMoradiaInputSchema(BaseSchema):
    """Endereço de moradia informado no aceite do convite, sem coordenadas."""

    logradouro = fields.String(required=True, validate=validate.Length(min=1, max=150))
    numero = fields.String(required=True, validate=validate.Length(min=1, max=20))
    bairro = fields.String(required=True, validate=validate.Length(min=1, max=100))
    cidade = fields.String(required=True, validate=validate.Length(min=1, max=100))
    estado = fields.String(required=True, validate=validate.Regexp(r"^[A-Za-z]{2}$"))
    cep = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=10))
    complemento = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(max=100)
    )


class EnderecoResponseSchema(BaseSchema):
    logradouro = fields.String(dump_default=None)
    numero = fields.String(dump_default=None)
    bairro = fields.String(dump_default=None)
    cidade = fields.String(dump_default=None)
    cep = fields.String(dump_default=None)
    latitude = fields.Float(dump_default=None)
    longitude = fields.Float(dump_default=None)


class EnderecoMoradiaResponseSchema(BaseSchema):
    logradouro = fields.String(dump_default=None)
    numero = fields.String(dump_default=None)
    bairro = fields.String(dump_default=None)
    cidade = fields.String(dump_default=None)
    estado = fields.String(dump_default=None)
    cep = fields.String(dump_default=None)
    complemento = fields.String(dump_default=None)
