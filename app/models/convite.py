import uuid

from sqlalchemy.dialects.postgresql import UUID

from .base import db

PENDENTE = "PENDENTE"  # na fila: o job ainda vai gerar link e PIN e enviar o e-mail
ENVIADO = "ENVIADO"
ACEITO = "ACEITO"
CANCELADO = "CANCELADO"
EXPIRADO = "EXPIRADO"
STATUS_DO_CONVITE = (PENDENTE, ENVIADO, ACEITO, CANCELADO, EXPIRADO)


class Convite(db.Model):
    """Convite para o aluno concluir o próprio cadastro. Token e PIN só existem em hash."""

    __tablename__ = "convite"
    __table_args__ = (
        db.Index("idx_convite_prefeitura_status", "prefeitura_id", "status"),
        # Um convite em aberto por e-mail e prefeitura.
        db.Index(
            "uq_convite_aberto_por_email",
            "prefeitura_id",
            "email",
            unique=True,
            postgresql_where=db.text("status IN ('PENDENTE', 'ENVIADO')"),
        ),
    )

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prefeitura_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("prefeitura.id", ondelete="CASCADE"), nullable=False
    )
    criado_por_id = db.Column(UUID(as_uuid=True), db.ForeignKey("usuario.id", ondelete="SET NULL"))

    # Pré-cadastro feito pelo gestor
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(20))
    ponto_id = db.Column(UUID(as_uuid=True), db.ForeignKey("ponto.id", ondelete="SET NULL"))
    instituicao_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("instituicao.id", ondelete="SET NULL")
    )
    rota_id = db.Column(UUID(as_uuid=True), db.ForeignKey("rota.id", ondelete="SET NULL"))

    status = db.Column(db.String(20), nullable=False, default=PENDENTE)
    token_hash = db.Column(db.String(64), unique=True)
    pin_hash = db.Column(db.String(64))
    expira_em = db.Column(db.DateTime(timezone=True))
    pin_tentativas = db.Column(db.Integer, nullable=False, default=0)
    envio_tentativas = db.Column(db.Integer, nullable=False, default=0)
    enviado_em = db.Column(db.DateTime(timezone=True))

    aceito_em = db.Column(db.DateTime(timezone=True))
    termos_versao = db.Column(db.String(20))
    aluno_id = db.Column(UUID(as_uuid=True), db.ForeignKey("aluno.usuario_id", ondelete="SET NULL"))

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now()
    )

    ponto = db.relationship("Ponto")
    instituicao = db.relationship("Instituicao")
    rota = db.relationship("Rota")
