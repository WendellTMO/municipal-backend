"""Testes unitários do envio de e-mail."""

import logging
from unittest.mock import patch

import pytest

from app.utils.email_sender import mail_configurado, send_email

SENHA = "senha-super-secreta-123"


def _config(app, server="smtp.exemplo.com", username="user@exemplo.com", password=SENHA):
    app.config["MAIL_SERVER"] = server
    app.config["MAIL_USERNAME"] = username
    app.config["MAIL_PASSWORD"] = password
    app.config["MAIL_PORT"] = 587
    app.config["MAIL_USE_TLS"] = True


@pytest.mark.parametrize(
    "server,username,password,esperado",
    [
        ("s", "u", "p", True),
        ("", "u", "p", False),
        ("s", "", "p", False),
        ("s", "u", "", False),
        (None, None, None, False),
    ],
)
def test_mail_configurado(app, server, username, password, esperado):
    with app.app_context():
        _config(app, server, username, password)
        assert mail_configurado() is esperado


def test_send_email_sem_config_retorna_false_sem_smtp(app, caplog):
    with app.app_context():
        _config(app, password="")
        with patch("app.utils.email_sender.smtplib.SMTP") as smtp:
            with caplog.at_level(logging.DEBUG):
                resultado = send_email("a@b.com", "assunto", "corpo")
        assert resultado is False
        smtp.assert_not_called()
        assert "não configurado" in caplog.text


def test_send_email_envia_com_timeout_e_nao_loga_credenciais(app, caplog):
    with app.app_context():
        _config(app)
        with patch("app.utils.email_sender.smtplib.SMTP") as smtp:
            with caplog.at_level(logging.DEBUG):
                resultado = send_email("a@b.com", "assunto", "corpo", "<p>corpo</p>")
        assert resultado is True
        smtp.assert_called_once_with("smtp.exemplo.com", 587, timeout=10)
        server = smtp.return_value.__enter__.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("user@exemplo.com", SENHA)
        server.sendmail.assert_called_once()
        assert SENHA not in caplog.text
        assert "user@exemplo.com" not in caplog.text


def test_send_email_falha_smtp_propaga_sem_vazar_senha(app, caplog):
    with app.app_context():
        _config(app)
        with patch("app.utils.email_sender.smtplib.SMTP", side_effect=OSError("fora")):
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(OSError):
                    send_email("a@b.com", "assunto", "corpo")
        assert SENHA not in caplog.text
