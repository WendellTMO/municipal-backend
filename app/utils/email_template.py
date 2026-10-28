"""Layout HTML dos e-mails transacionais do BusKá (tabelas e CSS inline, sem JS)."""

from html import escape

COR_AZUL = "#0347D0"
FONTE = "Inter, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
LOGO_CID = "logo-buska"
# Cores medidas nos pixels da logo antiga (buska-login-hero.png): "Bus" em degradê de
# amarelo (#FCC202) a laranja (#EE8502), média #F4A402; "Ká" em azul marinho #033871.
# Sobre o cabeçalho azul o marinho some, então lá "Ká" fica branco e "Bus" usa o amarelo claro.
AMARELO_CLARO = "#FCC202"
AMARELO = "#F4A402"
MARINHO = "#033871"


def _bloco_pin(pin: str) -> str:
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px auto 20px auto;"><tr>'
        f'<td align="center" style="border:2px solid {COR_AZUL};border-radius:12px;'
        'background-color:#F2F5FA;padding:14px 28px;">'
        '<div style="font-size:12px;color:#5B6B85;text-transform:uppercase;'
        'letter-spacing:1px;padding-bottom:6px;">Seu código de acesso (PIN)</div>'
        f'<div style="font-size:34px;font-weight:700;color:{COR_AZUL};'
        f'letter-spacing:10px;padding-left:10px;font-family:{FONTE};">{escape(pin)}</div>'
        "</td></tr></table>"
        '<p style="margin:0 0 20px 0;font-size:13px;line-height:19px;color:#5B6B85;'
        'text-align:center;">Este código é pessoal. Ninguém do BusKá pede o seu PIN.</p>'
    )


def _botao(texto: str, url: str) -> str:
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px auto 20px auto;"><tr>'
        f'<td align="center" bgcolor="{COR_AZUL}" style="border-radius:10px;">'
        f'<a href="{escape(url)}" target="_blank" '
        'style="display:inline-block;padding:16px 36px;font-size:17px;font-weight:700;'
        f'color:#FFFFFF;text-decoration:none;border-radius:10px;font-family:{FONTE};">'
        f"{escape(texto)}</a></td></tr></table>"
    )


def montar_email_html(
    titulo: str,
    preheader: str,
    saudacao: str,
    paragrafos: list[str],
    botao_texto: str,
    botao_url: str,
    pin: str | None = None,
    validade: str | None = None,
) -> str:
    """Devolve o HTML completo do e-mail. Todo texto recebido é escapado aqui dentro.

    O logo é referenciado por `cid:logo-buska`, anexado por `send_email(logo_inline=True)`.
    """
    texto_paragrafos = ""
    for paragrafo in paragrafos:
        texto_paragrafos += (
            '<p style="margin:0 0 16px 0;font-size:16px;line-height:24px;color:#2B3647;">'
            f"{escape(paragrafo)}</p>"
        )

    bloco_pin = ""
    if pin:
        bloco_pin = _bloco_pin(pin)

    bloco_validade = ""
    if validade:
        bloco_validade = (
            '<p style="margin:0 0 16px 0;font-size:14px;line-height:21px;color:#5B6B85;'
            f'text-align:center;">{escape(validade)}</p>'
        )

    url = escape(botao_url)
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(titulo)}</title></head>"
        f'<body style="margin:0;padding:0;background-color:#F2F5FA;font-family:{FONTE};">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#F2F5FA;'
        f'font-size:1px;line-height:1px;">{escape(preheader)}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'bgcolor="#F2F5FA"><tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;background-color:#FFFFFF;border-radius:16px;'
        'overflow:hidden;">'
        # cabeçalho
        f'<tr><td align="center" bgcolor="{COR_AZUL}" style="padding:24px 16px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="padding-right:12px;"><img src="cid:{LOGO_CID}" width="48" height="48" '
        'alt="BusKá" style="display:block;border:2px solid #FFFFFF;border-radius:12px;"></td>'
        f'<td style="font-size:28px;font-weight:700;color:#FFFFFF;font-family:{FONTE};">'
        f'<span style="color:{AMARELO_CLARO};">Bus</span>Ká</td>'
        "</tr></table></td></tr>"
        # conteúdo
        '<tr><td style="padding:32px 32px 16px 32px;">'
        f'<h1 style="margin:0 0 20px 0;font-size:26px;line-height:32px;color:#0F1B33;">'
        f"{escape(titulo)}</h1>"
        '<p style="margin:0 0 16px 0;font-size:16px;line-height:24px;color:#2B3647;">'
        f"{escape(saudacao)}</p>"
        f"{texto_paragrafos}{_botao(botao_texto, botao_url)}{bloco_pin}{bloco_validade}"
        '<p style="margin:0 0 8px 0;font-size:12px;line-height:18px;color:#8593A8;'
        'text-align:center;">Se o botão não funcionar, copie este link e cole no navegador:<br>'
        f'<a href="{url}" style="color:#8593A8;word-break:break-all;">{url}</a></p>'
        "</td></tr>"
        # rodapé
        '<tr><td align="center" style="padding:20px 32px 28px 32px;'
        'border-top:1px solid #E3E8F0;">'
        '<p style="margin:0 0 2px 0;font-size:16px;line-height:22px;font-weight:700;'
        f'color:{MARINHO};"><span style="color:{AMARELO};">Bus</span>Ká</p>'
        '<p style="margin:0 0 8px 0;font-size:12px;line-height:18px;color:#8593A8;">'
        "gestão inteligente do transporte escolar municipal</p>"
        '<p style="margin:0;font-size:12px;line-height:18px;color:#8593A8;">'
        "Esta é uma mensagem automática. Por favor, não responda a este e-mail.</p>"
        "</td></tr></table></td></tr></table></body></html>"
    )
