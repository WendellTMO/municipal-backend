"""Telemetria de uso do app: recebe lotes de eventos, limpa o que não pode ficar e grava.

O que entra é só nome do evento e números ou textos curtos (tela, tempo, resultado). Nunca texto
digitado, nome, e-mail, CPF ou coordenada: o app não manda isso e o serviço descarta chaves e
valores fora do formato. Os eventos ficam enquanto durar a análise da demonstração.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import ValidationError
from app.core.transaction import transactional
from app.models.base import db
from app.models.telemetria import EventoTelemetria
from app.models.user import User

MAX_EVENTOS_POR_LOTE = 50
TIPOS = {"tela", "acao", "erro", "api", "gps", "sessao", "toque"}
MAX_CHAVES_DE_PROPS = 20
MAX_TEXTO = 120
MAX_BYTES_DE_PROPS = 2000
PADRAO_NOME = re.compile(r"^[a-z0-9_.:\-/]{1,80}$")
PADRAO_CHAVE = re.compile(r"^[a-z0-9_]{1,40}$")
# O relógio do aparelho pode estar errado: fora desta janela vale a hora de chegada.
JANELA_PASSADO = timedelta(days=1)
JANELA_FUTURO = timedelta(minutes=5)


def _texto(valor: Any, limite: int) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    return texto[:limite]


def _limpar_props(props: Any) -> dict[str, Any] | None:
    """Só chave simples e valor escalar. Aninhado, lista e excesso são descartados."""
    if not isinstance(props, dict):
        return None
    limpo: dict[str, Any] = {}
    for chave, valor in props.items():
        if len(limpo) >= MAX_CHAVES_DE_PROPS:
            break
        if not isinstance(chave, str) or not PADRAO_CHAVE.match(chave):
            continue
        if isinstance(valor, bool) or isinstance(valor, int) or isinstance(valor, float):
            limpo[chave] = valor
        elif isinstance(valor, str):
            limpo[chave] = valor[:MAX_TEXTO]
    if not limpo:
        return None
    if len(json.dumps(limpo)) > MAX_BYTES_DE_PROPS:
        return None
    return limpo


def _hora_do_evento(epoch_ms: Any, agora: datetime) -> datetime:
    if isinstance(epoch_ms, bool) or not isinstance(epoch_ms, int | float):
        return agora
    try:
        momento = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return agora
    if momento < agora - JANELA_PASSADO or momento > agora + JANELA_FUTURO:
        return agora
    return momento


def registrar_lote(user_id: str, contexto: dict[str, Any], eventos: list[Any]) -> dict[str, int]:
    """Grava os eventos válidos do lote. Devolve quantos foram aceitos e descartados."""
    if len(eventos) > MAX_EVENTOS_POR_LOTE:
        raise ValidationError(f"O lote aceita no máximo {MAX_EVENTOS_POR_LOTE} eventos")

    usuario = db.session.get(User, user_id)
    papel = usuario.role.name if usuario is not None else None
    sessao_id = _texto(contexto.get("sessao_id"), 40)
    if sessao_id is None:
        raise ValidationError("sessao_id é obrigatório")

    agora = datetime.now(UTC)
    aceitos: list[EventoTelemetria] = []
    descartados = 0
    for bruto in eventos:
        if not isinstance(bruto, dict):
            descartados += 1
            continue
        tipo = bruto.get("tipo")
        nome = bruto.get("nome")
        if tipo not in TIPOS or not isinstance(nome, str) or not PADRAO_NOME.match(nome):
            descartados += 1
            continue
        aceitos.append(
            EventoTelemetria(
                usuario_id=usuario.id if usuario is not None else None,
                papel=papel,
                sessao_id=sessao_id,
                tipo=tipo,
                nome=nome,
                props=_limpar_props(bruto.get("props")),
                versao_app=_texto(contexto.get("versao_app"), 30),
                plataforma=_texto(contexto.get("plataforma"), 20),
                dispositivo=_texto(contexto.get("dispositivo"), 100),
                versao_so=_texto(contexto.get("versao_so"), 40),
                ocorrido_em=_hora_do_evento(bruto.get("em"), agora),
            )
        )

    if aceitos:
        with transactional():
            db.session.add_all(aceitos)
    return {"aceitos": len(aceitos), "descartados": descartados}
