from marshmallow import fields

from app.schemas.common import BaseSchema
from app.schemas.endereco_schema import EnderecoMoradiaResponseSchema

# ==========================================
# Input Schemas (Validation)
# ==========================================


class FcmTokenRequestSchema(BaseSchema):
    """Schema for updating the FCM token."""

    fcm_token = fields.String(required=True)


class FcmTokenResponseSchema(BaseSchema):
    """Schema for updating the FCM token response."""

    message = fields.String(required=True)


class UpdateProfileRequestSchema(BaseSchema):
    """Schema for updating user profile (PATCH /users/me)."""

    nome = fields.String(required=False)
    telefone = fields.String(required=False)
    receber_notificacoes = fields.Boolean(required=False)
    cnh = fields.String(required=False)


class MotoristaCreateRequestSchema(BaseSchema):
    """Schema for creating a new driver."""

    nome = fields.String(required=True)
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True)
    cpf = fields.String(required=True)
    telefone = fields.String(load_default=None)
    cnh = fields.String(required=True)


class ChangePasswordRequestSchema(BaseSchema):
    """Schema for changing password."""

    current_password = fields.String(required=True)
    new_password = fields.String(required=True)


class ChangePasswordResponseSchema(BaseSchema):
    """Schema for changing password response."""

    message = fields.String()


class UserResponseSchema(BaseSchema):
    """Schema for user response."""

    id = fields.String()
    prefeitura_id = fields.String()
    nome = fields.String()
    email = fields.String()
    telefone = fields.String()
    cpf = fields.String()

    role = fields.Method("get_role")
    status = fields.String(attribute="status.value")
    signup_completed_at = fields.DateTime(attribute="signup_completed_at")
    # Municipality info
    municipio_nome = fields.Method("get_municipio_nome")
    municipio_uf = fields.Method("get_municipio_uf")

    # Polymorphic fields (may not exist on all User subtypes)
    matricula = fields.String(dump_default=None)
    cnh = fields.String(dump_default=None)
    # Só Aluno tem endereço de moradia; para os outros papéis sai null.
    endereco = fields.Nested(
        EnderecoMoradiaResponseSchema, attribute="endereco_moradia", dump_default=None
    )

    def get_role(self, obj):
        return str(obj.role.value) if hasattr(obj.role, "value") else str(obj.role)

    def get_municipio_nome(self, obj):
        if obj.prefeitura:
            return obj.prefeitura.nome
        return None

    def get_municipio_uf(self, obj):
        if obj.prefeitura:
            return obj.prefeitura.estado
        return None


class UserListResponseSchema(BaseSchema):
    """Schema for user list response."""

    items = fields.List(fields.Nested(UserResponseSchema()), required=True)
    total = fields.Integer(required=True)
