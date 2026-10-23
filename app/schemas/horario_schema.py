from marshmallow import fields, validate

from app.schemas.common import BaseSchema


class HorarioCreateRequestSchema(BaseSchema):
    horario_saida = fields.Time(required=True, metadata={"description": "Horário de saída (HH:MM)"})
    sentido = fields.String(
        required=True,
        validate=validate.OneOf(["IDA", "VOLTA", "CIRCULAR"]),
        metadata={"description": "Sentido da viagem"},
    )
    dias = fields.List(
        fields.String(validate=validate.OneOf(["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"])),
        required=True,
        metadata={"description": "Lista de dias da semana"},
    )


class HorarioResponseSchema(BaseSchema):
    id = fields.String()
    horario_saida = fields.Time()
    sentido = fields.Method("get_sentido")
    dias = fields.Method("get_dias")

    def get_sentido(self, obj):
        # fields.String sobre o enum devolvia "SentidoViagem.IDA"
        return obj.sentido.value

    def get_dias(self, obj):
        return [d.dia.value if hasattr(d.dia, "value") else d.dia for d in obj.dias]


class HorarioListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(HorarioResponseSchema), required=True)
    total = fields.Integer(required=True)
