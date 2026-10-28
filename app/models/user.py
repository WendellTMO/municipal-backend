import uuid
from datetime import date

from sqlalchemy.dialects.postgresql import UUID

from .base import db
from .enum import UserRole, UserStatus
from .notificacao import Notificacao  # noqa: F401


class User(db.Model):
    __tablename__ = "usuario"
    __table_args__ = (db.Index("idx_usuario_prefeitura", "prefeitura_id"),)

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prefeitura_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("prefeitura.id", ondelete="CASCADE"), nullable=False
    )
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    telefone = db.Column(db.String(20))
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    receber_notificacoes = db.Column(db.Boolean, default=True, nullable=False)

    fcm_token = db.Column(db.String(255), nullable=True)

    role = db.Column(db.Enum(UserRole, name="user_role"), nullable=False, default=UserRole.ALUNO)
    status = db.Column(
        db.Enum(UserStatus, name="user_status"), nullable=False, default=UserStatus.PENDING_SIGNUP
    )
    signup_completed_at = db.Column(db.DateTime(timezone=True))

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now()
    )

    notificacoes = db.relationship(
        "Notificacao", backref="usuario", lazy=True, cascade="all, delete-orphan"
    )

    __mapper_args__ = {"polymorphic_identity": UserRole.USER, "polymorphic_on": role}

    @property
    def is_gestor(self):
        return self.role == UserRole.GESTOR


class Motorista(User):
    __tablename__ = "motorista"

    usuario_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    cnh = db.Column(db.String(20), unique=True, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": UserRole.MOTORISTA,
    }


class Gestor(User):
    __tablename__ = "gestor"

    usuario_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )

    __mapper_args__ = {
        "polymorphic_identity": UserRole.GESTOR,
    }


class Aluno(User):
    __tablename__ = "aluno"

    usuario_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    matricula = db.Column(db.String(50))

    # Guardian (single responsible person, replaces the old pai/mae pair)
    nome_responsavel = db.Column(db.String(100))
    cpf_responsavel = db.Column(db.String(14))

    # Minor / guardian consent flow
    data_nascimento = db.Column(db.Date)
    email_responsavel = db.Column(db.String(120))
    guardian_token = db.Column(db.String(64), unique=True)
    guardian_consented_at = db.Column(db.DateTime(timezone=True))

    instituicao_id = db.Column(UUID(as_uuid=True), db.ForeignKey("instituicao.id"))
    ponto_casa_id = db.Column(UUID(as_uuid=True), db.ForeignKey("ponto.id"))

    instituicao = db.relationship("Instituicao")
    ponto_casa = db.relationship("Ponto")
    # Endereço de moradia (Endereco.aluno_id). O banco apaga em cascata junto com a conta.
    endereco_moradia = db.relationship(
        "Endereco",
        foreign_keys="Endereco.aluno_id",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __mapper_args__ = {
        "polymorphic_identity": UserRole.ALUNO,
    }

    @property
    def is_minor(self) -> bool:
        if not self.data_nascimento:
            return False
        today = date.today()
        age = (
            today.year
            - self.data_nascimento.year
            - ((today.month, today.day) < (self.data_nascimento.month, self.data_nascimento.day))
        )
        return age < 18
