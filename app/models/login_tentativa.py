"""Falhas seguidas de login por e-mail, para a trava com espera exponencial."""

from .base import db


class LoginTentativa(db.Model):
    __tablename__ = "login_tentativa"

    # E-mail em minúsculas. Vale também para e-mail que não existe, para a resposta ser igual.
    chave = db.Column(db.String(160), primary_key=True)
    falhas = db.Column(db.Integer, nullable=False, default=0)
    bloqueado_ate = db.Column(db.DateTime(timezone=True), nullable=True)
    atualizado_em = db.Column(db.DateTime(timezone=True), nullable=False)
