from marshmallow import fields

from app.schemas.common import BaseSchema

# ==========================================
# Input Schemas (Validation)
# ==========================================


class PontoCreateRequestSchema(BaseSchema):
    """Schema for creating a new point."""

    apelido = fields.String(required=False, allow_none=True)
    latitude = fields.Float(required=True)
    longitude = fields.Float(required=True)


class PontoUpdateRequestSchema(BaseSchema):
    """Schema for updating a point (all fields optional)."""

    apelido = fields.String()
    latitude = fields.Float()
    longitude = fields.Float()


# ==========================================
# Response Schemas (Serialization)
# ==========================================


class PontoResponseSchema(BaseSchema):
    id = fields.UUID()
    apelido = fields.String()
    latitude = fields.Float()
    longitude = fields.Float()
    endereco = fields.String(dump_default=None)
    instituicao = fields.String(dump_default=None)


class PontoInstituicaoResponseSchema(BaseSchema):
    id = fields.String()
    nome = fields.String()
    tipo = fields.String()


class PontoFlatResponseSchema(BaseSchema):
    id = fields.String()
    apelido = fields.String()
    latitude = fields.Float()
    longitude = fields.Float()
    ordem = fields.Integer()
    # Só vem preenchido em GET /rotas/{id}/pontos; nos demais usos o campo é omitido.
    instituicao = fields.Nested(PontoInstituicaoResponseSchema, allow_none=True)


class PontoFlatListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(PontoFlatResponseSchema), required=True)
    total = fields.Integer(required=True)


class PontoListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(PontoResponseSchema), required=True)
    total = fields.Integer(required=True)
