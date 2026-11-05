"""Regras para escolher uma senha nova, no modelo do NIST SP 800-63B.

Tamanho mínimo e máximo, sem exigir "maiúscula + símbolo", e recusa de senha comum, ligada ao
usuário ou que já vazou em invasões públicas (consulta k-anonymity no Have I Been Pwned).
"""

import hashlib
import logging

import requests
from flask import current_app

from app.core.exceptions import ValidationError
from app.utils.security import SecurityConfig

logger = logging.getLogger(__name__)

TAMANHO_MAXIMO = 128
URL_VAZAMENTOS = "https://api.pwnedpasswords.com/range/"

# As mais usadas no Brasil e no mundo, em minúsculas. A consulta de vazamentos cobre o resto.
SENHAS_COMUNS = frozenset(
    {
        "12345678", "123456789", "1234567890", "12345678910", "11111111", "00000000",
        "87654321", "123123123", "password", "password1", "password123", "qwertyui",
        "qwerty123", "qwertyuiop", "abcd1234", "abc12345", "abcdefgh", "senha123",
        "senha1234", "senha12345", "minhasenha", "mudar123", "brasil123", "brasil2024",
        "iloveyou", "admin123", "administrador", "welcome1", "letmein1", "changeme",
        "buska123", "buska1234", "ufcg1234", "ufcg2024", "ufcg2025", "ufcg2026",
        "campinagrande", "paraiba123", "onibus123", "estudante", "estudante123",
        "flamengo", "corinthians", "palmeiras", "gabriel123", "123mudar", "1q2w3e4r",
        "q1w2e3r4", "zxcvbnm123", "asdfghjkl",
    }
)  # fmt: skip


def senha_vazada(senha: str) -> bool:
    """True se a senha aparece em vazamentos públicos. Se o serviço não responde, deixa passar.

    Só os 5 primeiros caracteres do SHA-1 saem do servidor, nunca a senha nem o hash inteiro.
    """
    if current_app.config.get("TESTING"):
        return False
    digest = hashlib.sha1(senha.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefixo, sufixo = digest[:5], digest[5:]
    try:
        resposta = requests.get(
            URL_VAZAMENTOS + prefixo, headers={"Add-Padding": "true"}, timeout=2
        )
        resposta.raise_for_status()
    except requests.RequestException:
        logger.warning("Consulta de senhas vazadas indisponível; seguindo sem ela.")
        return False
    for linha in resposta.text.splitlines():
        achado, _, vezes = linha.partition(":")
        if achado.strip() == sufixo and vezes.strip() not in ("", "0"):
            return True
    return False


def validar_senha_nova(senha: str, email: str = "", nome: str = "") -> str:
    """Devolve a senha se for aceitável. Senão levanta ValidationError dizendo o que ajustar."""
    minimo = SecurityConfig.MIN_PASSWORD_LENGTH
    if len(senha) < minimo:
        raise ValidationError(f"A nova senha deve ter no mínimo {minimo} caracteres")
    if len(senha) > TAMANHO_MAXIMO:
        raise ValidationError(f"A nova senha deve ter no máximo {TAMANHO_MAXIMO} caracteres")

    minuscula = senha.lower()
    if minuscula in SENHAS_COMUNS or len(set(minuscula)) == 1:
        raise ValidationError("Essa senha é muito comum. Escolha outra mais difícil de adivinhar")

    parte_do_email = email.split("@")[0].lower()
    if len(parte_do_email) >= 4 and parte_do_email in minuscula:
        raise ValidationError("A senha não pode conter o seu e-mail")
    primeiro_nome = nome.strip().split(" ")[0].lower() if nome.strip() else ""
    if len(primeiro_nome) >= 4 and minuscula == primeiro_nome:
        raise ValidationError("A senha não pode ser o seu nome")

    if senha_vazada(senha):
        raise ValidationError(
            "Essa senha apareceu em vazamentos de dados na internet. Escolha outra que você não use em outros sites"
        )
    return senha
