"""Send email via SMTP using app config."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

logger = logging.getLogger(__name__)


SMTP_TIMEOUT_SECONDS = 10


def mail_configurado() -> bool:
    """True só se MAIL_SERVER, MAIL_USERNAME e MAIL_PASSWORD estiverem preenchidos."""
    config = current_app.config
    if not config.get("MAIL_SERVER"):
        return False
    if not config.get("MAIL_USERNAME"):
        return False
    if not config.get("MAIL_PASSWORD"):
        return False
    return True


def send_email(
    to: str,
    subject: str,
    body_plain: str,
    body_html: str | None = None,
) -> bool:
    """Envia e-mail pelo SMTP configurado. False se o e-mail não está configurado.

    Falha de SMTP continua propagando a exceção para o chamador decidir.
    """
    if not mail_configurado():
        logger.warning(
            "E-mail não configurado (MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD). " "Envio ignorado."
        )
        return False

    mail_server = current_app.config["MAIL_SERVER"]
    mail_port = current_app.config.get("MAIL_PORT", 587)
    mail_username = current_app.config["MAIL_USERNAME"]
    mail_password = current_app.config["MAIL_PASSWORD"]
    mail_use_tls = current_app.config.get("MAIL_USE_TLS", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_username
    msg["To"] = to
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))

    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    logger.info("Enviando e-mail para %s via %s:%s", to, mail_server, mail_port)

    try:
        with smtplib.SMTP(mail_server, mail_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            if mail_use_tls:
                server.starttls()
            server.login(mail_username, mail_password)
            server.sendmail(mail_username, to, msg.as_string())

        logger.info("E-mail enviado para %s", to)
        return True

    except Exception:
        logger.exception("Falha ao enviar e-mail para %s", to)
        raise
