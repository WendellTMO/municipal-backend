from __future__ import annotations

from datetime import date, datetime
from typing import Any

from flask_jwt_extended import get_jwt_identity
from marshmallow import ValidationError as MarshmallowValidationError, fields, validates_schema
from marshmallow.validate import OneOf, Range

from app.models.enum import StatusViagem
from app.models.rota import RotaAluno
from app.schemas.common import BaseSchema
from app.schemas.validators import validate_uuid4

# -------------------------
# Common helpers / fields
# -------------------------


class DateISOField(fields.Field):
    """YYYY-MM-DD <-> datetime.date"""

    default_error_messages = {
        "invalid": "Data inválida. Use YYYY-MM-DD",
        "required": "Campo obrigatório",
    }

    def _deserialize(self, value: Any, attr: str | None, data: Any, **kwargs) -> date:
        if value is None:
            raise MarshmallowValidationError(self.error_messages["required"])

        if isinstance(value, date) and not isinstance(value, datetime):
            return value

        if isinstance(value, str):
            try:
                return datetime.strptime(value.strip(), "%Y-%m-%d").date()
            except ValueError:
                raise MarshmallowValidationError(self.error_messages["invalid"])

        raise MarshmallowValidationError(self.error_messages["invalid"])

    def _serialize(self, value: Any, attr: str | None, obj: Any, **kwargs) -> str | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        return str(value)


class EnumByNameField(fields.Field):
    """Accepts enum by NAME (e.g. 'AGENDADA') and returns Enum instance."""

    def __init__(self, enum_cls, **kwargs):
        super().__init__(**kwargs)
        self.enum_cls = enum_cls
        self.allowed = [e.name for e in enum_cls]

    def _deserialize(self, value: Any, attr: str | None, data: Any, **kwargs):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value
        if isinstance(value, str):
            v = value.strip()
            if v in self.allowed:
                return self.enum_cls[v]
        raise MarshmallowValidationError(f"Valor inválido. Use um de: {', '.join(self.allowed)}")

    def _serialize(self, value: Any, attr: str | None, obj: Any, **kwargs):
        if value is None:
            return None
        return value.name if hasattr(value, "name") else str(value)


# ==========================================
# Input Schemas (Validation)
# ==========================================


class ViagemCreateRequestSchema(BaseSchema):
    """Schema for creating a new trip."""

    rota_id = fields.UUID(required=True)
    data = fields.Date(required=True)


class ViagemLoteRequestSchema(BaseSchema):
    """POST /viagens/gerar-lote"""

    data = DateISOField(required=True)


class ViagemConfirmacaoRequestSchema(BaseSchema):
    """Schema for student trip confirmation."""

    confirmacao = fields.Boolean(required=True)
    ponto_embarque_id = fields.UUID(load_default=None, allow_none=True)

    @validates_schema
    def validate_confirmacao(self, data: dict[str, Any], **kwargs) -> None:
        if data.get("confirmacao") is True and not data.get("ponto_embarque_id"):
            raise MarshmallowValidationError(
                {"ponto_embarque_id": ["Para confirmar, selecione um ponto de embarque."]}
            )


class ViagemAcaoRequestSchema(BaseSchema):
    """PUT /viagens/<id>/acao"""

    acao = fields.String(required=True, validate=OneOf(["INICIAR", "FINALIZAR"]))


class ViagemListQuerySchema(BaseSchema):
    """GET /viagens?data_inicio=...&status=..."""

    # NOTE: these are query params, so everything comes as string.
    data_inicio = DateISOField(required=False, allow_none=True)
    data_fim = DateISOField(required=False, allow_none=True)

    status = EnumByNameField(StatusViagem, required=False, allow_none=True)
    motorista_id = fields.String(required=False, allow_none=True, validate=validate_uuid4)
    rota_id = fields.String(required=False, allow_none=True, validate=validate_uuid4)

    # Optional pagination (even if you don't use yet, it makes "total" correct later)
    page = fields.Integer(required=False, load_default=1, validate=Range(min=1))
    per_page = fields.Integer(required=False, load_default=20, validate=Range(min=1, max=100))

    @validates_schema
    def validate_date_range(self, data: dict[str, Any], **kwargs) -> None:
        di = data.get("data_inicio")
        df = data.get("data_fim")
        if di and df and df < di:
            raise MarshmallowValidationError({"data_fim": ["data_fim deve ser >= data_inicio."]})


# ==========================================
# Response Schemas (Serialization)
# ==========================================


class MessageResponseSchema(BaseSchema):
    message = fields.String(required=True)


class ViagemLoteResponseSchema(BaseSchema):
    total_rotas_analisadas = fields.Integer(required=True)
    viagens_criadas = fields.Integer(required=True)
    detalhes = fields.List(fields.String(), required=True)


class ViagemAlunoConfirmacaoResponseSchema(BaseSchema):
    aluno_id = fields.String()
    nome = fields.String(attribute="aluno.nome")
    confirmacao = fields.Boolean()
    ponto_embarque = fields.String(attribute="ponto_embarque.apelido")
    ponto_destino = fields.String(attribute="ponto_destino.apelido")
    instituicao = fields.Method("get_instituicao")

    def get_instituicao(self, obj):
        instituicao = obj.aluno.instituicao
        if instituicao is None:
            return None
        return {
            "id": str(instituicao.id),
            "nome": instituicao.nome,
            "tipo": instituicao.tipo.value,
        }


class ViagemPontoResponseSchema(BaseSchema):
    ponto_id = fields.String()
    apelido = fields.String(attribute="ponto.apelido")
    ordem = fields.Integer()
    visitado = fields.Boolean()
    chegada_real = fields.DateTime()


class ViagemResponseSchema(BaseSchema):
    id = fields.String()
    data = fields.Date()
    status = fields.Method("get_status")
    motorista_nome = fields.String(attribute="motorista.nome", dump_default="Sem Motorista")
    veiculo_placa = fields.String(attribute="veiculo.placa", dump_default="Sem Veículo")

    # Schedule info
    horario_inicio = fields.Method("get_horario_inicio")
    horario_fim = fields.DateTime(attribute="fim_real")
    inicio_real = fields.DateTime()  # Actual start time for elapsed calculation
    tipo = fields.Method("get_tipo")
    rota_id = fields.Method("get_rota_id")
    rota_nome = fields.Method("get_rota_nome")

    pontos = fields.List(fields.Nested(ViagemPontoResponseSchema), attribute="pontos_visitados")
    alunos = fields.List(
        fields.Nested(ViagemAlunoConfirmacaoResponseSchema), attribute="alunos_confirmados"
    )

    # Counts for dashboard
    total_alunos = fields.Method("get_total_alunos")
    alunos_confirmados_count = fields.Method("get_alunos_confirmados_count")

    def get_total_alunos(self, obj):
        """Total students enrolled in the route."""
        if obj.horario_rota and obj.horario_rota.rota:
            return len(obj.horario_rota.rota.alunos_inscritos)
        return 0

    def get_alunos_confirmados_count(self, obj):
        """Number of students who confirmed presence."""
        if obj.alunos_confirmados:
            return sum(1 for a in obj.alunos_confirmados if a.confirmacao)
        return 0

    def get_status(self, obj):
        """Get status as string."""
        if obj.status:
            return obj.status.name if hasattr(obj.status, "name") else str(obj.status)
        return "AGENDADA"

    def get_horario_inicio(self, obj):
        if obj.horario_rota:
            return str(obj.horario_rota.horario_saida)
        return None

    def get_tipo(self, obj):
        if obj.horario_rota:
            return obj.horario_rota.sentido.name
        return None

    def get_rota_id(self, obj):
        if obj.horario_rota and obj.horario_rota.rota:
            return str(obj.horario_rota.rota.id)
        return None

    def get_rota_nome(self, obj):
        if obj.horario_rota and obj.horario_rota.rota:
            return obj.horario_rota.rota.nome
        return None

    origem = fields.Method("get_origem")
    destino = fields.Method("get_destino")

    def get_origem(self, obj):
        if obj.horario_rota and obj.horario_rota.rota:
            rota = obj.horario_rota.rota
            if rota.pontos_padrao and len(rota.pontos_padrao) > 0:
                primeiro_ponto = sorted(rota.pontos_padrao, key=lambda p: p.ordem)[0]
                if primeiro_ponto.ponto:
                    return primeiro_ponto.ponto.apelido
        return None

    def get_destino(self, obj):
        if obj.horario_rota and obj.horario_rota.rota:
            rota = obj.horario_rota.rota
            if rota.pontos_padrao and len(rota.pontos_padrao) > 0:
                ultimo_ponto = sorted(rota.pontos_padrao, key=lambda p: p.ordem)[-1]
                if ultimo_ponto.ponto:
                    return ultimo_ponto.ponto.apelido
        return None

    alunos_embarcados_count = fields.Method("get_alunos_embarcados_count")

    def get_alunos_embarcados_count(self, obj):
        """Conta apenas os alunos que a catraca/geofencing registrou (embarcou=True)"""
        if obj.alunos_confirmados:
            return sum(1 for a in obj.alunos_confirmados if a.embarcou)
        return 0


class ViagemAgendaAlunoResponseSchema(BaseSchema):
    """
    Agenda payload for a student's upcoming trips.

    Viagem.alunos_confirmados carries every student confirmed on the trip, so
    the confirmation fields are resolved from the caller's JWT identity rather
    than from the position of the record in that list.
    """

    viagem_id = fields.Method("get_viagem_id")
    data = fields.Date()
    dia_semana = fields.Method("get_dia_semana")
    horario_saida = fields.Method("get_horario_saida")
    sentido = fields.Method("get_sentido")
    rota_id = fields.Method("get_rota_id")
    rota_nome = fields.Method("get_rota_nome")
    status_confirmacao = fields.Method("get_status_confirmacao")
    ponto_embarque_id = fields.Method("get_ponto_embarque_id")
    # Trip status and capacity — exposed so students can see bus occupancy
    status_viagem = fields.Method("get_status_viagem")
    alunos_confirmados_count = fields.Method("get_alunos_confirmados_count")
    total_alunos = fields.Method("get_total_alunos")

    def get_status_viagem(self, obj):
        if obj.status:
            return obj.status.name if hasattr(obj.status, "name") else str(obj.status)
        return "AGENDADA"

    def get_alunos_confirmados_count(self, obj):
        if obj.alunos_confirmados:
            return sum(1 for a in obj.alunos_confirmados if a.confirmacao)
        return 0

    def get_total_alunos(self, obj):
        """Total students subscribed to the route."""
        if obj.horario_rota and obj.horario_rota.rota:
            return RotaAluno.query.filter_by(rota_id=obj.horario_rota.rota.id).count()
        return 0

    def _find_confirmacao(self, obj):
        """
        Return the confirmation record belonging to the student making the
        request, or None if there is none.

        Viagem.alunos_confirmados holds every student confirmed on the trip,
        so it must be filtered here. When the caller cannot be identified we
        return None instead of guessing, so that a record is never attributed
        to the wrong student.
        """
        try:
            aluno_id = get_jwt_identity()
        except RuntimeError:
            # Dumped outside a request carrying a JWT.
            return None

        if not aluno_id:
            return None

        for record in obj.alunos_confirmados or []:
            if str(record.aluno_id) == str(aluno_id):
                return record
        return None

    def get_viagem_id(self, obj):
        return str(obj.id)

    def get_dia_semana(self, obj):
        dias_map = {0: "SEG", 1: "TER", 2: "QUA", 3: "QUI", 4: "SEX", 5: "SAB", 6: "DOM"}
        return dias_map.get(obj.data.weekday()) if obj.data else None

    def get_horario_saida(self, obj):
        return str(obj.horario_rota.horario_saida) if obj.horario_rota else None

    def get_sentido(self, obj):
        return obj.horario_rota.sentido.name if obj.horario_rota else None

    def get_rota_id(self, obj):
        rota = obj.horario_rota.rota if obj.horario_rota else None
        return str(rota.id) if rota else None

    def get_rota_nome(self, obj):
        rota = obj.horario_rota.rota if obj.horario_rota else None
        return rota.nome if rota else None

    def get_status_confirmacao(self, obj):
        c = self._find_confirmacao(obj)
        return bool(c.confirmacao) if c else False

    def get_ponto_embarque_id(self, obj):
        c = self._find_confirmacao(obj)
        return str(c.ponto_embarque_id) if (c and c.ponto_embarque_id) else None


class ViagemListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(ViagemResponseSchema))
    total = fields.Integer()


class ViagemAgendaAlunoListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(ViagemAgendaAlunoResponseSchema))
    total = fields.Integer()
