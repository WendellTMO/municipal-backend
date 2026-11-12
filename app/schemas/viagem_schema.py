from __future__ import annotations

from datetime import date, datetime
from typing import Any

from flask import g
from flask_jwt_extended import get_jwt_identity
from marshmallow import (
    ValidationError as MarshmallowValidationError,
    fields,
    post_dump,
    validates_schema,
)
from marshmallow.validate import Length, OneOf, Range

from app.models.base import db
from app.models.enum import SentidoViagem, StatusViagem, UserRole
from app.models.geo import Instituicao
from app.models.rota import RotaAluno, pontos_no_sentido
from app.schemas.common import BaseSchema
from app.models.user import User
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
    ponto_desembarque_id = fields.UUID(load_default=None, allow_none=True)
    instituicao_id = fields.UUID(load_default=None, allow_none=True)
    lembrar_escolha = fields.Boolean(load_default=False)


class ViagemAcaoRequestSchema(BaseSchema):
    """PUT /viagens/<id>/acao"""

    acao = fields.String(
        required=True, validate=OneOf(["INICIAR", "FINALIZAR", "MARCAR_REALIZADA"])
    )


class ViagemPontoCreateRequestSchema(BaseSchema):
    """POST /viagens/<id>/pontos: ponto existente (ponto_id) ou novo (latitude e longitude)."""

    ponto_id = fields.UUID(required=False)
    apelido = fields.String(required=False, allow_none=True, validate=Length(max=100))
    latitude = fields.Float(required=False, validate=Range(min=-90, max=90))
    longitude = fields.Float(required=False, validate=Range(min=-180, max=180))
    posicao = fields.String(load_default="proxima", validate=OneOf(["proxima", "fim"]))

    @validates_schema
    def validate_ponto_ou_coordenadas(self, data: dict[str, Any], **kwargs) -> None:
        tem_ponto = "ponto_id" in data
        tem_coordenadas = "latitude" in data or "longitude" in data
        if tem_ponto and tem_coordenadas:
            raise MarshmallowValidationError("Informe ponto_id ou latitude e longitude, não ambos.")
        if not tem_ponto and ("latitude" not in data or "longitude" not in data):
            raise MarshmallowValidationError("Informe ponto_id ou latitude e longitude.")


class ChegadaEventoSchema(BaseSchema):
    """Uma chegada detectada pelo app do motorista (hora do aparelho)."""

    ponto_id = fields.UUID(required=True)
    detectado_em = fields.DateTime(required=True)
    latitude = fields.Float(required=False, validate=Range(min=-90, max=90))
    longitude = fields.Float(required=False, validate=Range(min=-180, max=180))
    origem = fields.String(load_default="manual", validate=OneOf(["auto", "manual", "conferencia"]))


class ViagemChegadasRequestSchema(BaseSchema):
    """POST /viagens/<id>/pontos-visitados: lote de chegadas, até 100 por chamada."""

    eventos = fields.List(
        fields.Nested(ChegadaEventoSchema), required=True, validate=Length(min=1, max=100)
    )


class ViagemCancelarRequestSchema(BaseSchema):
    """PUT /viagens/<id>/cancelar: o motivo é opcional."""

    motivo = fields.String(load_default=None, allow_none=True, validate=Length(max=200))


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


def _instituicoes_por_ponto(viagem):
    """Instituições dos pontos confirmados da viagem, numa consulta só (guardada na viagem)."""
    guardado = getattr(viagem, "_instituicoes_por_ponto", None)
    if guardado is not None:
        return guardado

    ponto_ids = set()
    for confirmacao in viagem.alunos_confirmados:
        if confirmacao.ponto_embarque_id is not None:
            ponto_ids.add(confirmacao.ponto_embarque_id)
        if confirmacao.ponto_destino_id is not None:
            ponto_ids.add(confirmacao.ponto_destino_id)

    por_ponto = {}
    if ponto_ids:
        for instituicao in Instituicao.query.filter(Instituicao.ponto_id.in_(ponto_ids)).all():
            por_ponto[instituicao.ponto_id] = instituicao
    viagem._instituicoes_por_ponto = por_ponto
    return por_ponto


def _instituicao_da_viagem(obj):
    """Instituição em que o aluno sobe (VOLTA) ou desce (IDA) nesta viagem.

    Vem do ponto confirmado, porque o aluno pode usar uma instituição que não é a dele.
    Sem ponto de instituição (circular ou sem confirmação), vale a instituição do aluno.
    """
    propria = obj.aluno.instituicao
    sentido = obj.viagem.horario_rota.sentido if obj.viagem and obj.viagem.horario_rota else None
    ponto_id = None
    if sentido == SentidoViagem.IDA:
        ponto_id = obj.ponto_destino_id
    elif sentido == SentidoViagem.VOLTA:
        ponto_id = obj.ponto_embarque_id
    if ponto_id is None or (propria is not None and propria.ponto_id == ponto_id):
        return propria
    escolhida = _instituicoes_por_ponto(obj.viagem).get(ponto_id)
    return escolhida or propria


def _gestor_que_esta_lendo():
    """O gestor que fez o pedido (para esconder alunos de outro município), ou None.

    Guardado em `g`: a lista de alunos de uma viagem repete a pergunta para cada aluno.
    """
    try:
        if hasattr(g, "_gestor_leitor"):
            return g._gestor_leitor
        usuario_id = get_jwt_identity()
    except RuntimeError:
        return None
    gestor = None
    if usuario_id:
        usuario = db.session.get(User, usuario_id)
        if usuario is not None and usuario.role == UserRole.GESTOR:
            gestor = usuario
    g._gestor_leitor = gestor
    return gestor


class ViagemAlunoConfirmacaoResponseSchema(BaseSchema):
    aluno_id = fields.String()
    nome = fields.String(attribute="aluno.nome")
    confirmacao = fields.Boolean()
    ponto_embarque = fields.String(attribute="ponto_embarque.apelido")
    ponto_destino = fields.String(attribute="ponto_destino.apelido")
    ponto_embarque_id = fields.Method("get_ponto_embarque_id")
    ponto_destino_id = fields.Method("get_ponto_destino_id")
    instituicao = fields.Method("get_instituicao")

    def get_ponto_embarque_id(self, obj):
        if obj.ponto_embarque_id is None:
            return None
        return str(obj.ponto_embarque_id)

    def get_ponto_destino_id(self, obj):
        if obj.ponto_destino_id is None:
            return None
        return str(obj.ponto_destino_id)

    def get_instituicao(self, obj):
        instituicao = _instituicao_da_viagem(obj)
        if instituicao is None:
            return None
        return {
            "id": str(instituicao.id),
            "nome": instituicao.nome,
            "tipo": instituicao.tipo.value,
        }

    @post_dump(pass_original=True)
    def esconder_aluno_de_outro_municipio(self, dados, original, **kwargs):
        """Para o gestor, o aluno de outra prefeitura aparece só como "outro município".

        Sem nome, sem id e sem instituição. O motorista e o próprio aluno não passam por aqui.
        """
        gestor = _gestor_que_esta_lendo()
        aluno = getattr(original, "aluno", None)
        dados["outro_municipio"] = False
        if gestor is None or aluno is None or aluno.prefeitura_id == gestor.prefeitura_id:
            return dados
        origem = aluno.prefeitura
        dados["outro_municipio"] = True
        dados["aluno_id"] = None
        dados["nome"] = "Aluno de outro município"
        dados["instituicao"] = None
        dados["municipio_origem"] = f"{origem.nome}/{origem.estado}" if origem else None
        return dados


class ViagemPontoResponseSchema(BaseSchema):
    ponto_id = fields.String()
    apelido = fields.String(attribute="ponto.apelido")
    latitude = fields.Float(attribute="ponto.latitude")
    longitude = fields.Float(attribute="ponto.longitude")
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
    realizada_sem_app = fields.Boolean()
    motivo_cancelamento = fields.String(allow_none=True)
    km_real = fields.Float(allow_none=True)  # só existe em viagem finalizada pelo app
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
            pontos = pontos_no_sentido(rota.pontos_padrao, obj.horario_rota.sentido)
            if pontos:
                primeiro_ponto = sorted(pontos, key=lambda p: p.ordem)[0]
                if primeiro_ponto.ponto:
                    return primeiro_ponto.ponto.apelido
        return None

    def get_destino(self, obj):
        if obj.horario_rota and obj.horario_rota.rota:
            rota = obj.horario_rota.rota
            pontos = pontos_no_sentido(rota.pontos_padrao, obj.horario_rota.sentido)
            if pontos:
                ultimo_ponto = sorted(pontos, key=lambda p: p.ordem)[-1]
                if ultimo_ponto.ponto:
                    return ultimo_ponto.ponto.apelido
        return None

    alunos_embarcados_count = fields.Method("get_alunos_embarcados_count")

    def get_alunos_embarcados_count(self, obj):
        """Conta apenas os alunos que a catraca/geofencing registrou (embarcou=True)"""
        if obj.alunos_confirmados:
            return sum(1 for a in obj.alunos_confirmados if a.embarcou)
        return 0


class ViagemMinhasQuerySchema(BaseSchema):
    """GET /viagens/minhas (motorista): periodo, limit, offset, viagem_id e rota_id, opcionais."""

    periodo = fields.String(load_default=None, validate=OneOf(["proximas", "historico"]))
    limit = fields.Integer(load_default=100, validate=Range(min=1, max=100))
    offset = fields.Integer(load_default=0, validate=Range(min=0))
    viagem_id = fields.UUID(load_default=None)
    rota_id = fields.UUID(load_default=None)


class ViagemAgendaQuerySchema(BaseSchema):
    """GET /viagens/aluno/agenda?limit=..&offset=..&rota_id=.. (tudo opcional)."""

    # Padrão 50: o app antigo não manda limit e não deve baixar a agenda inteira.
    limit = fields.Integer(load_default=50, validate=Range(min=1, max=100))
    offset = fields.Integer(load_default=0, validate=Range(min=0))
    rota_id = fields.UUID(load_default=None)


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
    ponto_destino_id = fields.Method("get_ponto_destino_id")
    precisa_escolher_ponto = fields.Method("get_precisa_escolher_ponto")
    # Trip status and capacity — exposed so students can see bus occupancy
    status_viagem = fields.Method("get_status_viagem")
    motivo_cancelamento = fields.String(allow_none=True)
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
        pre_calculado = getattr(obj, "total_alunos_rota", None)
        if pre_calculado is not None:
            return pre_calculado
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
        if c and c.ponto_embarque_id:
            return str(c.ponto_embarque_id)
        padrao = getattr(obj, "ponto_embarque_sugerido_id", None)
        return str(padrao) if padrao else None

    def get_ponto_destino_id(self, obj):
        c = self._find_confirmacao(obj)
        if c and c.ponto_destino_id:
            return str(c.ponto_destino_id)
        padrao = getattr(obj, "ponto_destino_sugerido_id", None)
        return str(padrao) if padrao else None

    def get_precisa_escolher_ponto(self, obj):
        c = self._find_confirmacao(obj)
        if c and c.confirmacao:
            return False
        return bool(getattr(obj, "precisa_escolher_ponto", False))


class ViagemListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(ViagemResponseSchema))
    total = fields.Integer()


class ViagemAgendaAlunoListResponseSchema(BaseSchema):
    items = fields.List(fields.Nested(ViagemAgendaAlunoResponseSchema))
    total = fields.Integer()
