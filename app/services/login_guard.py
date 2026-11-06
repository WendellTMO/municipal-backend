"""Trava de login por e-mail com espera que dobra a cada nova falha (backoff exponencial).

As 4 primeiras falhas seguidas não travam. A 5ª trava por 30 segundos e cada falha seguinte dobra
a espera (60 s, 2 min, 4 min, 8 min) até o teto de 15 minutos. Enquanto trava, nem a senha certa
entra, e a tentativa feita durante a trava não conta. Login certo zera a contagem.

A chave é o e-mail, existente ou não, para a resposta ser a mesma nos dois casos.
shortcut: não há limite por IP, porque o IP real não chega confiável à API, e quem testa muitos
e-mails de um IP só é contido pela trava de cada e-mail. Revisar com o limitador do PR 89.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import RateLimitError
from app.core.transaction import transactional
from app.models.base import db
from app.models.login_tentativa import LoginTentativa

FALHAS_LIVRES = 4
ESPERA_BASE_SEGUNDOS = 30
ESPERA_MAXIMA_SEGUNDOS = 15 * 60
# Falha antiga demais não pesa: a contagem recomeça se a última foi há mais de um dia.
VALIDADE_DA_CONTAGEM = timedelta(days=1)


def espera_em_segundos(falhas: int) -> int:
    """Quanto a trava dura depois da falha de número `falhas`."""
    excesso = falhas - FALHAS_LIVRES
    if excesso <= 0:
        return 0
    # O expoente é limitado para o número não crescer sem necessidade.
    expoente = min(excesso - 1, 10)
    return min(ESPERA_BASE_SEGUNDOS * 2**expoente, ESPERA_MAXIMA_SEGUNDOS)


def _chave(email: str) -> str:
    return email.strip().lower()[:160]


def _texto_da_espera(segundos: float) -> str:
    segundos = int(segundos) + 1
    if segundos < 60:
        return f"{segundos} segundos"
    minutos = (segundos + 59) // 60
    return f"{minutos} minutos" if minutos > 1 else "1 minuto"


def exigir_sem_trava(email: str) -> None:
    """Levanta 429 se este e-mail está travado. Não conta como tentativa."""
    registro = db.session.get(LoginTentativa, _chave(email))
    if registro is None or registro.bloqueado_ate is None:
        return
    agora = datetime.now(UTC)
    if registro.bloqueado_ate > agora:
        restante = (registro.bloqueado_ate - agora).total_seconds()
        raise RateLimitError(f"Muitas tentativas. Tente de novo em {_texto_da_espera(restante)}.")


def registrar_falha(email: str) -> int:
    """Soma uma falha e trava se passou do limite. Devolve a espera aplicada, em segundos."""
    chave = _chave(email)
    agora = datetime.now(UTC)
    limite = agora - VALIDADE_DA_CONTAGEM

    with transactional():
        # Um só comando no banco, para duas falhas ao mesmo tempo não se perderem.
        comando = (
            insert(LoginTentativa)
            .values(chave=chave, falhas=1, atualizado_em=agora)
            .on_conflict_do_update(
                index_elements=["chave"],
                set_={
                    "falhas": case(
                        (LoginTentativa.atualizado_em < limite, 1),
                        else_=LoginTentativa.falhas + 1,
                    ),
                    "atualizado_em": agora,
                },
            )
            .returning(LoginTentativa.falhas)
        )
        falhas = db.session.execute(comando).scalar_one()

        espera = espera_em_segundos(falhas)
        if espera > 0:
            registro = db.session.get(LoginTentativa, chave)
            registro.bloqueado_ate = agora + timedelta(seconds=espera)

        # Limpeza de quem sumiu: mantém a tabela pequena mesmo com e-mails inventados.
        LoginTentativa.query.filter(LoginTentativa.atualizado_em < limite).delete()
    return espera


def limpar(email: str) -> None:
    """Zera a contagem depois de um login certo ou de uma senha redefinida."""
    registro = db.session.get(LoginTentativa, _chave(email))
    if registro is None:
        return
    with transactional():
        db.session.delete(registro)
