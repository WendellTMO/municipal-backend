import uuid

from sqlalchemy.dialects.postgresql import UUID

from .base import db


class Prefeitura(db.Model):
    __tablename__ = "prefeitura"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = db.Column(db.String(150), nullable=False)
    estado = db.Column(db.String(2), nullable=False)
    codigo_ibge = db.Column(db.String(10), nullable=False, unique=True, index=True)
    ativo = db.Column(db.Boolean, server_default="true")
    # Quando ligado, alunos de outras prefeituras podem buscar e se inscrever nas rotas desta.
    aceita_alunos_de_fora = db.Column(db.Boolean, nullable=False, server_default="false")

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    usuarios = db.relationship("User", backref=db.backref("prefeitura", lazy="joined"), lazy=True)
