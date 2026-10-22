from marshmallow import fields, validate

from app.schemas.common import BaseSchema


class FeedbackCreateRequestSchema(BaseSchema):
    tipo = fields.String(required=True, validate=validate.OneOf(["BUG", "SUGESTAO", "DUVIDA"]))
    mensagem = fields.String(required=True, validate=validate.Length(min=10, max=2000))
    tela = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=100))
    versao_app = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=30))
    plataforma = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["android", "ios", "web"]),
    )
