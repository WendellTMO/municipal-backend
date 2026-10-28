from marshmallow import fields, validate

from app.schemas.common import BaseSchema
from app.schemas.endereco_schema import (
    EnderecoInputSchema,
    EnderecoMoradiaInputSchema,
    EnderecoMoradiaResponseSchema,
)
from app.schemas.validators import (
    validate_cpf,
    validate_optional_cpf,
    validate_optional_phone,
    validate_optional_string,
)


class AlunoProvisionAccountRequestSchema(BaseSchema):
    """Gestor creates a minimal Aluno account (credentials + identity)."""

    nome = fields.String(required=True, validate=validate.Length(min=1))
    email = fields.Email(required=True, error_messages={"invalid": "Email inválido"})
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1))
    cpf = fields.String(required=True, validate=validate_cpf)
    telefone = fields.String(load_default=None, allow_none=True, validate=validate_optional_phone)


class AlunoSelfSignupRequestSchema(BaseSchema):
    """Aluno self-signs up for an account."""

    nome = fields.String(required=True, validate=validate.Length(min=1))
    email = fields.Email(required=True, error_messages={"invalid": "Email inválido"})
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1))
    cpf = fields.String(required=True, validate=validate_cpf)
    telefone = fields.String(load_default=None, allow_none=True, validate=validate_optional_phone)

    matricula = fields.String(required=True, validate=validate.Length(min=1))
    instituicao_id = fields.UUID(required=True)

    # Date of birth — determines whether guardian consent is required
    data_nascimento = fields.Date(required=True, format="%Y-%m-%d")

    # Guardian (required when minor, optional for adults)
    nome_responsavel = fields.String(
        load_default=None, allow_none=True, validate=validate_optional_string
    )
    cpf_responsavel = fields.String(
        load_default=None, allow_none=True, validate=validate_optional_cpf
    )
    email_responsavel = fields.Email(load_default=None, allow_none=True)

    endereco_casa = fields.Nested(EnderecoInputSchema, required=True)


class AlunoMeUpdateRequestSchema(BaseSchema):
    """Aluno updates their profile (partial update).

    Sem load_default: campo ausente não entra em `data` e o serviço não o toca.
    """

    nome = fields.String(allow_none=True, validate=validate_optional_string)
    telefone = fields.String(allow_none=True, validate=validate_optional_phone)

    matricula = fields.String(allow_none=True, validate=validate_optional_string)
    nome_responsavel = fields.String(allow_none=True, validate=validate_optional_string)
    cpf_responsavel = fields.String(allow_none=True, validate=validate_optional_cpf)

    endereco_casa = fields.Nested(EnderecoInputSchema, allow_none=True)
    # Endereço de moradia (Endereco.aluno_id), o mesmo formato que o GET devolve.
    endereco = fields.Nested(EnderecoMoradiaInputSchema, allow_none=True)


class AlunoGuardianConsentPublicSchema(BaseSchema):
    """Public info returned to the guardian consent screen."""

    nome = fields.String()
    data_nascimento = fields.Date(dump_default=None)
    is_minor = fields.Boolean()
    guardian_consented_at = fields.DateTime(dump_default=None)


class AlunoResponseSchema(BaseSchema):
    id = fields.UUID()
    nome = fields.String()
    email = fields.Email(dump_default=None)
    telefone = fields.String(dump_default=None)
    cpf = fields.String(dump_default=None)
    matricula = fields.String()
    escola = fields.String(attribute="instituicao.nome", dump_default=None)
    instituicao_id = fields.UUID(dump_default=None)

    status = fields.String(attribute="status.value", dump_default=None)
    signup_completed_at = fields.DateTime(dump_default=None)

    # Minor / guardian
    data_nascimento = fields.Date(dump_default=None)
    is_minor = fields.Boolean(dump_default=False)
    email_responsavel = fields.Email(dump_default=None)
    nome_responsavel = fields.String(dump_default=None)
    cpf_responsavel = fields.String(dump_default=None)
    guardian_consented_at = fields.DateTime(dump_default=None)

    endereco = fields.Nested(
        EnderecoMoradiaResponseSchema, attribute="endereco_moradia", dump_default=None
    )


class AlunoListResponseSchema(BaseSchema):
    """Gestor views a list of Alunos (pagination)."""

    items = fields.List(fields.Nested(AlunoResponseSchema()), required=True)
    total = fields.Integer(required=True)
