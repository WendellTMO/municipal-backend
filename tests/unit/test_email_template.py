"""Testes do layout HTML dos e-mails e do envio com logo inline."""

import smtplib

from app.utils.email_sender import send_email
from app.utils.email_template import montar_email_html


def _html(**extra):
    dados = {
        "titulo": "Titulo",
        "preheader": "Previa do email",
        "saudacao": "Olá, Ana!",
        "paragrafos": ["Primeiro texto."],
        "botao_texto": "Abrir",
        "botao_url": "https://buska.test/convite/abc",
    }
    dados.update(extra)
    return montar_email_html(**dados)


def test_template_tem_botao_logo_preheader_e_link():
    pagina = _html(validade="Vale por 7 dias.")
    assert 'lang="pt-BR"' in pagina
    assert "cid:logo-buska" in pagina
    assert 'bgcolor="#0347D0"' in pagina
    assert 'href="https://buska.test/convite/abc"' in pagina
    assert "Previa do email" in pagina
    assert "Vale por 7 dias." in pagina
    assert "mensagem automática" in pagina


def test_template_pin_so_aparece_quando_informado():
    assert "483920" in _html(pin="483920")
    assert "Ninguém do BusKá pede o seu PIN" in _html(pin="483920")
    assert "PIN" not in _html()


def test_template_escapa_conteudo_malicioso():
    pagina = _html(
        saudacao="<script>alert(1)</script>",
        botao_url='https://x.test/"><img src=x onerror=alert(1)>',
        pin="<b>1</b>",
    )
    assert "<script>" not in pagina
    assert "<img src=x" not in pagina
    assert "<b>1</b>" not in pagina
    assert "&lt;script&gt;" in pagina


class _SmtpFalso:
    enviadas: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def sendmail(self, de, para, texto):
        _SmtpFalso.enviadas.append(texto)


def _enviar(app, monkeypatch, **extra):
    app.config.update(MAIL_SERVER="smtp.t", MAIL_USERNAME="u@t", MAIL_PASSWORD="p")
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    _SmtpFalso.enviadas = []
    with app.app_context():
        send_email("a@b.com", "assunto", "texto simples", "<p>oi</p>", **extra)
    return _SmtpFalso.enviadas[0]


def test_send_email_com_logo_inline_monta_related(app, monkeypatch):
    bruto = _enviar(app, monkeypatch, logo_inline=True)
    assert "multipart/related" in bruto
    assert "Content-ID: <logo-buska>" in bruto
    assert "image/png" in bruto


def test_send_email_sem_logo_nao_anexa_imagem(app, monkeypatch):
    bruto = _enviar(app, monkeypatch)
    assert "multipart/related" not in bruto
    assert "image/png" not in bruto
