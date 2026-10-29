"""Testes do layout HTML dos e-mails e do envio com logo inline."""

import smtplib

from app.utils.email_sender import send_email
from app.utils.email_template import montar_email_html, passo_numerado


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
    assert "gestão inteligente do transporte escolar municipal" in pagina


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


def test_template_sem_links_app_nao_tem_passos():
    pagina = _html()
    assert "Baixe o app" not in pagina
    assert "Conclua seu cadastro" not in pagina


def test_template_passos_na_ordem_com_links_e_numeros():
    pagina = _html(
        pin="483920",
        links_app=("https://buska.test/buska.apk", "https://buska.test"),
    )
    posicoes = []
    for titulo in ["Conclua seu cadastro", "Baixe o app", "Abra o app e entre"]:
        assert pagina.count(titulo) == 1
        posicoes.append(pagina.index(titulo))
    assert posicoes == sorted(posicoes)
    assert pagina.index("483920") < pagina.index("Baixe o app")
    for numero in "123":
        assert (
            f"font-weight:700;color:#FFFFFF;font-family:Inter, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;\">{numero}</td>"
            in pagina
        )
    assert pagina.count('bgcolor="#0347D0"') >= 5
    assert 'href="https://buska.test/buska.apk"' in pagina
    assert "Baixar o app para Android" in pagina
    assert "fontes desconhecidas" in pagina
    assert "Entre com o e-mail e a senha que você criou no cadastro." in pagina
    assert pagina.index("Abra o app e entre") < pagina.index("No iPhone, o app chega em breve")
    assert "Por enquanto use o BusKá pelo navegador" in pagina
    assert "—" not in pagina and "–" not in pagina


def test_passo_numerado_escapa_titulo():
    bloco = passo_numerado(2, "<i>x</i>", "<p>corpo</p>")
    assert "<i>" not in bloco
    assert "&lt;i&gt;" in bloco
    assert "<p>corpo</p>" in bloco


def test_template_passos_escapam_urls():
    pagina = _html(links_app=('https://x.test/"><b>', "https://y.test/<i>"))
    assert "<b>" not in pagina and "<i>" not in pagina
