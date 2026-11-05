import base64
import binascii

from marshmallow import ValidationError, fields, validate, validates

from app.schemas.common import BaseSchema


CAPTURA_MAX_BYTES = 400 * 1024
JPEG_ASSINATURA = b"\xff\xd8\xff"


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
    dispositivo = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=100))
    versao_so = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=40))
    tamanho_tela = fields.String(
        load_default=None, allow_none=True, validate=validate.Regexp(r"^\d{2,5}x\d{2,5}$")
    )
    # JPEG em base64, sem o prefixo "data:". Só o app envia; fica guardado para quem analisa o relato.
    captura = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(max=CAPTURA_MAX_BYTES * 4 // 3 + 8)
    )

    @validates("captura")
    def validar_captura(self, valor: str | None, **kwargs: object) -> None:
        if valor is None:
            return
        try:
            bruto = base64.b64decode(valor, validate=True)
        except (binascii.Error, ValueError):
            raise ValidationError("A captura precisa estar em base64.")
        if len(bruto) > CAPTURA_MAX_BYTES:
            raise ValidationError("A captura passou de 400 KB.")
        if not bruto.startswith(JPEG_ASSINATURA):
            raise ValidationError("A captura precisa ser um JPEG.")
