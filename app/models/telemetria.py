"""Evento de uso do app (tela aberta, ação, erro, tempo de chamada), sem dado pessoal no conteúdo."""

from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import db


class EventoTelemetria(db.Model):
    __tablename__ = "evento_telemetria"
    __table_args__ = (
        db.Index("idx_evento_telemetria_recebido", "recebido_em"),
        db.Index("idx_evento_telemetria_tipo_nome", "tipo", "nome"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    # Some se o usuário for apagado, e o evento deixa de apontar para alguém.
    usuario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("usuario.id", ondelete="SET NULL"))
    papel = db.Column(db.String(12))
    sessao_id = db.Column(db.String(40), nullable=False)
    tipo = db.Column(db.String(12), nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    props = db.Column(JSONB)
    versao_app = db.Column(db.String(30))
    plataforma = db.Column(db.String(20))
    dispositivo = db.Column(db.String(100))
    versao_so = db.Column(db.String(40))
    ocorrido_em = db.Column(db.DateTime(timezone=True), nullable=False)
    recebido_em = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
