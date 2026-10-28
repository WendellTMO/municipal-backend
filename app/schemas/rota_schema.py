from marshmallow import fields, validate

from app.schemas.common import BaseSchema

from .horario_schema import HorarioResponseSchema
from .ponto_schema import PontoFlatResponseSchema

# ==========================================
# Input Schemas (Validation)
# ==========================================


class RotaPontoAddRequestSchema(BaseSchema):
    """Schema for adding a point to a route."""

    ponto_id = fields.String(required=True)
    ordem = fields.Integer(required=True)


class RotaPontosAddRequestSchema(BaseSchema):
    """Schema for adding points to a route."""

    pontos = fields.List(fields.Nested(RotaPontoAddRequestSchema), required=True)


class RotaInstituicoesOrdemRequestSchema(BaseSchema):
    """Schema for replacing the institution order of a route."""

    instituicao_ids = fields.List(fields.UUID(), required=True)


class RotaHorarioCreateRequestSchema(BaseSchema):
    """Schema for route schedule input."""

    horario_saida = fields.String(required=True)
    sentido = fields.String(required=True, validate=validate.OneOf(["IDA", "VOLTA", "CIRCULAR"]))
    dias = fields.List(fields.String(), required=True)


class RotaCreateRequestSchema(BaseSchema):
    """Schema for creating a new route."""

    nome = fields.String(required=True)
    motorista_padrao_id = fields.String(load_default=None)
    veiculo_padrao_id = fields.String(load_default=None)
    pontos = fields.List(fields.Nested(RotaPontoAddRequestSchema), load_default=[])
    horarios = fields.List(fields.Nested(RotaHorarioCreateRequestSchema), load_default=[])


class RotaUpdateRequestSchema(BaseSchema):
    """Schema for updating a route.

    All fields are optional. Only fields present in the request body are updated.
    Pass null explicitly to clear an assignment (e.g. motorista_padrao_id=null).
    """

    nome = fields.String()
    motorista_padrao_id = fields.String(allow_none=True)
    veiculo_padrao_id = fields.String(allow_none=True)


class RotaInscricaoRequestSchema(BaseSchema):
    """Schema for route subscription action."""

    acao = fields.String(required=True, validate=validate.OneOf(["inscrever", "desinscrever"]))


class MeuPontoEmbarqueRequestSchema(BaseSchema):
    """PUT /rotas/<id>/meu-ponto-embarque"""

    ponto_embarque_id = fields.UUID(load_default=None, allow_none=True)
    ponto_desembarque_id = fields.UUID(load_default=None, allow_none=True)


# ==========================================
# Response Schemas (Serialization)
# ==========================================


class RotaResponseSchema(BaseSchema):
    id = fields.String()
    nome = fields.String()
    motorista_id = fields.Method("get_motorista_id")
    veiculo_id = fields.Method("get_veiculo_id")
    prefeitura_id = fields.String()
    municipio_nome = fields.Method("get_municipio_nome")
    municipio_uf = fields.Method("get_municipio_uf")

    def get_motorista_id(self, obj):
        return str(obj.motorista_padrao_id) if obj.motorista_padrao_id else None

    def get_veiculo_id(self, obj):
        return str(obj.veiculo_padrao_id) if obj.veiculo_padrao_id else None

    def get_municipio_nome(self, obj):
        if obj.prefeitura:
            return obj.prefeitura.nome
        return None

    def get_municipio_uf(self, obj):
        if obj.prefeitura:
            return obj.prefeitura.estado
        return None


class RotaDetailResponseSchema(RotaResponseSchema):
    """Extended schema with nested relationships."""

    pontos = fields.Method("get_pontos")
    horarios = fields.Nested(HorarioResponseSchema, many=True, attribute="grade_horarios")

    def get_pontos(self, obj):
        return PontoFlatResponseSchema(many=True).dump(
            [rota_ponto.ponto for rota_ponto in obj.pontos_padrao]
        )


class RotaListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(RotaResponseSchema), required=True)
    total = fields.Integer(required=True)


class InstituicaoOrdemItemSchema(BaseSchema):
    instituicao_id = fields.String()
    nome = fields.String()
    tipo = fields.String()
    ordem = fields.Integer()


class InstituicaoOrdemListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(InstituicaoOrdemItemSchema), required=True)
    total = fields.Integer(required=True)
