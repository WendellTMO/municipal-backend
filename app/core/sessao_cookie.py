"""Sessão por cookie httpOnly, usada pelo site. O app segue com o token no cabeçalho Authorization."""

from typing import Any

from flask import Response, jsonify, make_response, request
from flask_jwt_extended import set_access_cookies

# O site manda este cabeçalho no login e na troca de senha. Sem ele a resposta não muda.
CABECALHO_COOKIE = "X-Sessao-Cookie"


def pede_cookie() -> bool:
    return request.headers.get(CABECALHO_COOKIE) == "1"


def resposta_com_cookie(corpo: dict[str, Any]) -> Response:
    """Põe o token no cookie e tira do corpo, assim o JavaScript da página nunca o vê."""
    token = corpo["token"]
    sem_token = {chave: valor for chave, valor in corpo.items() if chave != "token"}
    resposta = make_response(jsonify(sem_token), 200)
    set_access_cookies(resposta, token)
    return resposta
