import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import db
from .enum import DiaDaSemana, SentidoViagem


class Rota(db.Model):
    __tablename__ = "rota"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prefeitura_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("prefeitura.id", ondelete="CASCADE"), nullable=False
    )
    nome = db.Column(db.String(100), nullable=False)

    motorista_padrao_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("motorista.usuario_id", ondelete="SET NULL")
    )

    veiculo_padrao_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("onibus.id", ondelete="SET NULL")
    )

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now()
    )

    prefeitura = relationship("Prefeitura")
    motorista_padrao = relationship("Motorista")
    veiculo_padrao = relationship("Onibus")

    pontos_padrao = relationship(
        "RotaPonto", back_populates="rota", order_by="RotaPonto.ordem", cascade="all, delete-orphan"
    )

    grade_horarios = relationship(
        "HorarioRota", back_populates="rota", cascade="all, delete-orphan"
    )
    alunos_inscritos = relationship("RotaAluno", backref="rota", cascade="all, delete-orphan")


class RotaPonto(db.Model):
    __tablename__ = "rota_ponto"

    rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("rota.id", ondelete="CASCADE"), primary_key=True
    )

    ponto_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("ponto.id", ondelete="RESTRICT"), primary_key=True
    )

    ordem = db.Column(db.Integer, nullable=False)

    rota = relationship("Rota", back_populates="pontos_padrao")
    ponto = relationship("Ponto")


class HorarioRota(db.Model):
    __tablename__ = "horario_rota"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("rota.id", ondelete="CASCADE"), nullable=False
    )

    horario_saida = db.Column(db.Time, nullable=False)
    sentido = db.Column(db.Enum(SentidoViagem, name="sentido_viagem"), nullable=False)

    rota = relationship("Rota", back_populates="grade_horarios")

    dias = relationship("DiasOperacao", back_populates="horario", cascade="all, delete-orphan")


class DiasOperacao(db.Model):
    __tablename__ = "dias_operacao"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    horario_rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("horario_rota.id", ondelete="CASCADE"), nullable=False
    )

    dia = db.Column(db.Enum(DiaDaSemana, name="dia_da_semana"), nullable=False)

    horario = relationship("HorarioRota", back_populates="dias")


class RotaAluno(db.Model):
    __tablename__ = "rota_aluno"

    rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("rota.id", ondelete="CASCADE"), primary_key=True
    )
    aluno_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("aluno.usuario_id", ondelete="CASCADE"), primary_key=True
    )

    data_inscricao = db.Column(db.DateTime, server_default=db.func.now())
    # Ponto da rota em que o aluno costuma embarcar; a ida desembarca na instituição
    # e a volta desembarca neste mesmo ponto.
    ponto_embarque_padrao_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("ponto.id", ondelete="SET NULL"), nullable=True
    )
    ponto_embarque_padrao = db.relationship("Ponto", foreign_keys=[ponto_embarque_padrao_id])


class RotaInstituicaoOrdem(db.Model):
    """Ordem em que o motorista visita as instituições de uma rota."""

    __tablename__ = "rota_instituicao_ordem"
    __table_args__ = (db.Index("idx_rota_instituicao_ordem_rota_ordem", "rota_id", "ordem"),)

    rota_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("rota.id", ondelete="CASCADE"), primary_key=True
    )
    instituicao_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("instituicao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordem = db.Column(db.Integer, nullable=False)

    instituicao = relationship("Instituicao")
