"""CEP service - consulta de endereço na ViaCEP.

Endpoint público (o aluno usa antes de ter conta), por isso tem limite por IP.
"""

import logging
import time
from typing import Any

import requests
from requests.exceptions import ConnectionError, Timeout

from app.core.exceptions import AppError, NotFoundError, RateLimitError, ValidationError

logger = logging.getLogger(__name__)

_VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
_TIMEOUT_SECONDS = 5

_LIMITE_POR_MINUTO = 30
_JANELA_SEGUNDOS = 60

# shortcut: limite e cache vivem na memória de cada processo (com N workers o limite
# real é N vezes maior e o cache não é compartilhado). Trocar por Redis ou tabela no
# Postgres quando houver mais de um worker em produção ou abuso real.
_acessos_por_ip: dict[str, list[float]] = {}
_cache_por_cep: dict[str, dict[str, str]] = {}
_CACHE_MAX = 500


def _normalizar_cep(cep: str) -> str:
    digitos = cep
    if len(cep) == 9 and cep[5] == "-":
        digitos = cep[:5] + cep[6:]
    if len(digitos) != 8 or not digitos.isascii() or not digitos.isdigit():
        raise ValidationError("CEP inválido: informe 8 dígitos, com ou sem hífen")
    return digitos


def _checar_limite(ip: str) -> None:
    agora = time.monotonic()
    recentes: list[float] = []
    for instante in _acessos_por_ip.get(ip, []):
        if agora - instante < _JANELA_SEGUNDOS:
            recentes.append(instante)

    if len(recentes) >= _LIMITE_POR_MINUTO:
        _acessos_por_ip[ip] = recentes
        raise RateLimitError("Muitas consultas de CEP. Tente novamente em instantes")

    recentes.append(agora)
    _acessos_por_ip[ip] = recentes


def consultar_cep(cep: str, ip: str) -> dict[str, str]:
    """Devolve {cep, logradouro, bairro, cidade, estado} do CEP informado.

    Raises:
        ValidationError: formato do CEP inválido.
        RateLimitError (429): IP passou do limite por minuto.
        NotFoundError (404): ViaCEP não conhece o CEP.
        AppError (503): ViaCEP fora do ar, com erro ou lenta demais.
    """
    digitos = _normalizar_cep(cep)
    _checar_limite(ip)

    if digitos in _cache_por_cep:
        return _cache_por_cep[digitos]

    url = _VIACEP_URL.format(cep=digitos)
    try:
        response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data: Any = response.json()
    except Timeout:
        logger.warning("ViaCEP request timed out")
        raise AppError("Serviço de CEP indisponível (timeout)", 503, "CEP_TIMEOUT")
    except (ConnectionError, requests.HTTPError, ValueError):
        logger.warning("ViaCEP unavailable or returned an invalid response")
        raise AppError("Serviço de CEP indisponível", 503, "CEP_UNAVAILABLE")

    if not isinstance(data, dict):
        raise AppError("Serviço de CEP indisponível", 503, "CEP_UNAVAILABLE")

    # ViaCEP responde 200 com {"erro": true} (ou "true") quando o CEP não existe.
    if str(data.get("erro", "")).lower() == "true":
        raise NotFoundError("CEP não encontrado")

    resultado = {
        "cep": digitos,
        "logradouro": data.get("logradouro") or "",
        "bairro": data.get("bairro") or "",
        "cidade": data.get("localidade") or "",
        "estado": data.get("uf") or "",
    }

    if len(_cache_por_cep) >= _CACHE_MAX:
        _cache_por_cep.clear()
    _cache_por_cep[digitos] = resultado
    return resultado
