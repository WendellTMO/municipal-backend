import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import db
from .enum import TipoInstituicao


class Ponto(db.Model):
    __tablename__ = "ponto"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prefeitura_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("prefeitura.id", ondelete="CASCADE"), nullable=False
    )
    latitude = db.Column(db.Numeric(10, 8), nullable=False)
    longitude = db.Column(db.Numeric(11, 8), nullable=False)
    apelido = db.Column(db.String(100))
    # Note: 'geom' column is a generated column in PostgreSQL, managed by DB

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    endereco = relationship(
        "Endereco", back_populates="ponto", uselist=False, cascade="all, delete-orphan"
    )
    instituicao = relationship(
        "Instituicao", back_populates="ponto", uselist=False, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "apelido": self.apelido,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            # Optional: return extra data if available
            "endereco": self.endereco.logradouro if self.endereco else None,
            "instituicao": self.instituicao.nome if self.instituicao else None,
        }


class Endereco(db.Model):
    __tablename__ = "endereco"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logradouro = db.Column(db.String(150))
    numero = db.Column(db.String(20))
    bairro = db.Column(db.String(100))
    cidade = db.Column(db.String(100))
    cep = db.Column(db.String(10))
    estado = db.Column(db.String(2))
    complemento = db.Column(db.String(100))
    # Endereço de moradia do aluno, sem ponto: some junto com a conta.
    aluno_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("aluno.usuario_id", ondelete="CASCADE"), nullable=True
    )

    ponto_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("ponto.id", ondelete="SET NULL"),
        nullable=True,  # Matches DB: ON DELETE SET NULL
    )

    ponto = relationship("Ponto", back_populates="endereco")


class Instituicao(db.Model):
    __tablename__ = "instituicao"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    fonte = db.Column(db.String(20), nullable=False)  # "EMEC" | "INEP" | "MANUAL"
    codigo_externo = db.Column(db.String(30), nullable=False)

    nome = db.Column(db.String(200), nullable=False)
    sigla = db.Column(db.String(40))
    cnpj = db.Column(db.String(20))

    tipo = db.Column(
        db.Enum(TipoInstituicao, name="tipo_instituicao"),
        nullable=False,
    )

    uf = db.Column(db.String(2), nullable=False, index=True)

    prefeitura_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("prefeitura.id"),
        nullable=False,
        index=True,
    )

    prefeitura = db.relationship("Prefeitura", lazy="joined")

    situacao = db.Column(db.String(80))
    categoria_administrativa = db.Column(db.String(80))
    organizacao_academica = db.Column(db.String(80))

    ponto_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("ponto.id", ondelete="CASCADE"),
        nullable=True,
    )

    ponto = relationship("Ponto", back_populates="instituicao")

    __table_args__ = (
        db.UniqueConstraint(
            "fonte",
            "codigo_externo",
            name="uq_instituicao_fonte_codigo_externo",
        ),
    )
