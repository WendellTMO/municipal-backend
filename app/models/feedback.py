import uuid

from sqlalchemy.dialects.postgresql import UUID

from .base import db
from .enum import TipoFeedback


class Feedback(db.Model):
    __tablename__ = "feedback"
    __table_args__ = (db.Index("idx_feedback_created_at", "created_at"),)

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # SET NULL: o relato sobrevive à exclusão da conta de quem enviou.
    usuario_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )
    prefeitura_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("prefeitura.id"),
        nullable=True,
    )

    tipo = db.Column(db.Enum(TipoFeedback, name="tipo_feedback"), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    tela = db.Column(db.String(100), nullable=True)
    versao_app = db.Column(db.String(30), nullable=True)
    plataforma = db.Column(db.String(20), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
