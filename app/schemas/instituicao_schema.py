from marshmallow import fields, validate

from app.schemas.common import BaseSchema
from app.schemas.endereco_schema import EnderecoResponseSchema


class InstituicaoCreateRequestSchema(BaseSchema):
    nome = fields.String(required=True)
    cnpj = fields.String(required=True)
    tipo = fields.String(
        required=True,
        validate=validate.OneOf(
            [
                "INSTITUTO_FEDERAL",
                "UNIVERSIDADE_PUBLICA",
                "UNIVERSIDADE_PRIVADA",
                "ESCOLA_PUBLICA",
                "ESCOLA_PRIVADA",
                "ESCOLA_COMUNITARIA",
            ]
        ),
        metadata={"description": "Tipo da instituição conforme modelo"},
    )
    endereco = fields.Nested(EnderecoResponseSchema, required=True)


class InstituicaoResponseSchema(BaseSchema):
    id = fields.String(dump_default=None)
    nome = fields.String(dump_default=None)
    cnpj = fields.String(dump_default=None)
    tipo = fields.Method("get_tipo")

    def get_tipo(self, obj):
        return str(obj.tipo.value) if hasattr(obj.tipo, "value") else str(obj.tipo)

    sigla = fields.String(dump_default=None)
    uf = fields.String(dump_default=None)
    endereco = fields.Nested(EnderecoResponseSchema, attribute="ponto.endereco")
    latitude = fields.Float(attribute="ponto.latitude", dump_default=None)
    longitude = fields.Float(attribute="ponto.longitude", dump_default=None)


class InstituicaoListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(InstituicaoResponseSchema()), required=True)
    total = fields.Integer(required=True)


class InstituicaoBuscaQuerySchema(BaseSchema):
    """GET /instituicoes/busca?q=...&limit=..."""

    q = fields.String(load_default="", validate=validate.Length(max=100))
    limit = fields.Integer(load_default=20, validate=validate.Range(min=1, max=50))


class InstituicaoBuscaItemSchema(BaseSchema):
    """Só o que a lista de escolha precisa; não carrega ponto nem endereço."""

    id = fields.String()
    nome = fields.String()
    sigla = fields.String(dump_default=None)
    uf = fields.String(dump_default=None)


class InstituicaoBuscaResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(InstituicaoBuscaItemSchema()), required=True)
    total = fields.Integer(required=True)


class InstituicaoListQuerySchema(BaseSchema):
    search = fields.String(required=False)
    limit = fields.Integer(required=False, dump_default=10)
