import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import db
from .enum import StatusViagem


class Viagem(db.Model):
    __tablename__ = "viagem"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data = db.Column(db.Date, nullable=False)
    horario_rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("horario_rota.id", ondelete="SET NULL"), nullable=True
    )

    motorista_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("motorista.usuario_id", ondelete="RESTRICT"),
        nullable=True,
    )
    veiculo_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("onibus.id", ondelete="RESTRICT"), nullable=True
    )

    status = db.Column(db.Enum(StatusViagem, name="status_viagem"), default=StatusViagem.AGENDADA)

    inicio_real = db.Column(db.DateTime(timezone=True), nullable=True)
    fim_real = db.Column(db.DateTime(timezone=True), nullable=True)
    km_real = db.Column(db.Numeric(10, 2), nullable=True)

    motorista_lat = db.Column(db.Numeric(10, 8), nullable=True)
    motorista_lon = db.Column(db.Numeric(11, 8), nullable=True)
    motorista_gps_hora = db.Column(db.DateTime(timezone=True), nullable=True)
    localizacao_solicitada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    # it must change to a version 2
    aviso_24h_enviado = db.Column(db.Boolean, default=False, nullable=False)
    aviso_10min_enviado = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now()
    )

    horario_rota = relationship("HorarioRota")
    motorista = relationship("Motorista")
    veiculo = relationship("Onibus")

    pontos_visitados = relationship(
        "ViagemPonto",
        back_populates="viagem",
        order_by="ViagemPonto.ordem",
        cascade="all, delete-orphan",
    )

    alunos_confirmados = relationship(
        "AlunosConfirmados", back_populates="viagem", cascade="all, delete-orphan"
    )


class ViagemPonto(db.Model):
    """
    Controla o progresso da viagem ponto a ponto.
    """

    __tablename__ = "viagem_ponto"

    viagem_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("viagem.id", ondelete="CASCADE"), primary_key=True
    )
    ponto_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("ponto.id", ondelete="RESTRICT"), primary_key=True
    )

    ordem = db.Column(db.Integer, nullable=False)
    visitado = db.Column(db.Boolean, server_default="false")

    chegada_estimada = db.Column(db.DateTime(timezone=True), nullable=True)
    chegada_real = db.Column(db.DateTime(timezone=True), nullable=True)

    aviso_aproximacao_enviado = db.Column(db.Boolean, server_default="false", nullable=False)

    viagem = relationship("Viagem", back_populates="pontos_visitados")
    ponto = relationship("Ponto")


class AlunosConfirmados(db.Model):
    __tablename__ = "alunos_confirmados"

    viagem_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("viagem.id", ondelete="CASCADE"), primary_key=True
    )

    aluno_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("aluno.usuario_id", ondelete="CASCADE"), primary_key=True
    )

    confirmacao = db.Column(db.Boolean, server_default="true")

    ponto_embarque_id = db.Column(UUID(as_uuid=True), db.ForeignKey("ponto.id"))

    ponto_destino_id = db.Column(UUID(as_uuid=True), db.ForeignKey("ponto.id"))

    viagem = relationship("Viagem", back_populates="alunos_confirmados")
    aluno = relationship("Aluno")

    ponto_embarque = relationship("Ponto", foreign_keys=[ponto_embarque_id])

    ponto_destino = relationship("Ponto", foreign_keys=[ponto_destino_id])

    embarcou = db.Column(db.Boolean, default=False, nullable=False)

    tentativas_auto_checkin = db.Column(db.Integer, default=0, nullable=False)

    aluno_lat = db.Column(db.Numeric(10, 8), nullable=True)
    aluno_lon = db.Column(db.Numeric(11, 8), nullable=True)
    aluno_gps_hora = db.Column(db.DateTime(timezone=True), nullable=True)


class TelemetriaViagem(db.Model):
    __tablename__ = "telemetria_viagem"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    viagem_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("viagem.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    latitude = db.Column(db.Numeric(10, 8), nullable=False)
    longitude = db.Column(db.Numeric(11, 8), nullable=False)

    timestamp = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    viagem = relationship(
        "Viagem",
        backref=db.backref("rastros_telemetria", lazy="dynamic", cascade="all, delete-orphan"),
    )
