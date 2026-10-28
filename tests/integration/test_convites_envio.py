"""Job de envio dos convites: processar_envios e job_convites."""

import email
import logging
import re
from unittest.mock import MagicMock, patch

import pytest

from app.models.convite import ENVIADO, PENDENTE, Convite
from app.services import convite_service
from app.tasks.convite_tasks import job_convites

pytestmark = pytest.mark.integration

SMTP = "app.utils.email_sender.smtplib.SMTP"


@pytest.fixture()
def mail(app, monkeypatch):
    """E-mail configurado e FRONTEND_URL definido."""
    monkeypatch.setitem(app.config, "MAIL_SERVER", "smtp.exemplo.test")
    monkeypatch.setitem(app.config, "MAIL_USERNAME", "envio@exemplo.test")
    monkeypatch.setitem(app.config, "MAIL_PASSWORD", "segredo")
    monkeypatch.setitem(app.config, "FRONTEND_URL", "https://app.exemplo.test")


@pytest.fixture()
def sem_mail(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_SERVER", "")
    monkeypatch.setitem(app.config, "MAIL_USERNAME", "")
    monkeypatch.setitem(app.config, "MAIL_PASSWORD", "")
    monkeypatch.setitem(app.config, "FRONTEND_URL", "https://app.exemplo.test")


def _pendente(gestor, _db, email_aluno="ana@exemplo.test"):
    r = gestor.client.post(
        "/v1/convites/", json={"convites": [{"nome": "Ana Souza", "email": email_aluno}]}
    )
    assert r.status_code == 201
    return _db.session.get(Convite, r.get_json()["items"][0]["id"])


def _corpo(smtp_mock, tipo="plain"):
    """Texto do e-mail enviado, decodificado."""
    sendmail = smtp_mock.return_value.__enter__.return_value.sendmail
    mensagem = email.message_from_string(sendmail.call_args.args[2])
    for parte in mensagem.walk():
        if parte.get_content_subtype() == tipo:
            return parte.get_payload(decode=True).decode("utf-8")
    raise AssertionError("parte não encontrada")


def test_envio_gera_link_e_pin_que_funcionam(gestor, client, mail, _db):
    convite = _pendente(gestor, _db)
    with patch(SMTP) as smtp:
        assert convite_service.processar_envios() == 1

    texto = _corpo(smtp)
    token = re.search(r"https://app\.exemplo\.test/convite/(\S+)", texto).group(1)
    pin = re.search(r"\(PIN\): (\d{6})", texto).group(1)
    assert "—" not in texto and "–" not in texto
    assert "<a href" in _corpo(smtp, "html")
    assert "https://app.exemplo.test/buska.apk" in texto
    assert "No iPhone, use o BusKá pelo navegador: https://app.exemplo.test" in texto
    html = _corpo(smtp, "html")
    assert 'href="https://app.exemplo.test/buska.apk"' in html
    assert "Baixar o app para Android" in html
    assert smtp.return_value.__enter__.return_value.sendmail.call_args.args[1] == "ana@exemplo.test"

    _db.session.refresh(convite)
    assert convite.status == ENVIADO and convite.enviado_em is not None
    assert token not in (convite.token_hash, convite.pin_hash)
    assert pin != convite.pin_hash

    r = client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin})
    assert r.status_code == 200


def test_reenviar_rotaciona_link_e_pin(gestor, client, mail, _db):
    convite = _pendente(gestor, _db)
    with patch(SMTP) as smtp:
        convite_service.processar_envios()
    primeiro = re.search(r"/convite/(\S+)", _corpo(smtp)).group(1)

    assert gestor.client.post(f"/v1/convites/{convite.id}/reenviar").status_code == 200
    with patch(SMTP) as smtp:
        assert convite_service.processar_envios() == 1
    segundo = re.search(r"/convite/(\S+)", _corpo(smtp)).group(1)

    assert primeiro != segundo
    assert (
        client.post(f"/v1/convites/aceite/{primeiro}/validar", json={"pin": "1"}).status_code == 404
    )


def test_tres_falhas_param_de_tentar(gestor, mail, _db):
    convite = _pendente(gestor, _db)
    with patch(SMTP, side_effect=OSError("smtp fora")):
        for _ in range(5):
            convite_service.processar_envios()
    _db.session.refresh(convite)
    assert convite.status == PENDENTE
    assert convite.envio_tentativas == 3
    assert convite.token_hash is None and convite.pin_hash is None

    # Reenviar zera a contagem e o convite volta a ser tentado.
    gestor.client.post(f"/v1/convites/{convite.id}/reenviar")
    with patch(SMTP):
        assert convite_service.processar_envios() == 1


def test_sem_mail_em_producao_mantem_fila_e_nao_loga_credenciais(
    gestor, sem_mail, monkeypatch, caplog, _db
):
    monkeypatch.setenv("FLASK_ENV", "production")
    convite = _pendente(gestor, _db)
    with caplog.at_level(logging.DEBUG):
        assert convite_service.processar_envios() == 0
    _db.session.refresh(convite)
    assert convite.status == PENDENTE and convite.token_hash is None
    assert "/convite/" not in caplog.text


def test_sem_mail_em_desenvolvimento_loga_link_e_pin(gestor, sem_mail, monkeypatch, caplog, _db):
    monkeypatch.setenv("FLASK_ENV", "development")
    convite = _pendente(gestor, _db)
    with caplog.at_level(logging.WARNING):
        assert convite_service.processar_envios() == 1
    _db.session.refresh(convite)
    assert convite.status == ENVIADO
    assert re.search(r"https://app\.exemplo\.test/convite/\S+ PIN \d{6}", caplog.text)


def test_frontend_url_vazio_mantem_fila(gestor, mail, app, monkeypatch, _db):
    monkeypatch.setitem(app.config, "FRONTEND_URL", "")
    convite = _pendente(gestor, _db)
    with patch(SMTP) as smtp:
        assert convite_service.processar_envios() == 0
    smtp.assert_not_called()
    _db.session.refresh(convite)
    assert convite.status == PENDENTE


def test_job_convites_usa_o_app_do_scheduler(gestor, mail, app, _db):
    convite = _pendente(gestor, _db)
    with patch("app.tasks.convite_tasks.scheduler", MagicMock(app=app)), patch(SMTP):
        job_convites()
    _db.session.refresh(convite)
    assert convite.status == ENVIADO
