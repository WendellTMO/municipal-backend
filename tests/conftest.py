import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import event

from app import create_app
from app.models.base import db
from app.models.enum import DiaDaSemana, SentidoViagem, StatusViagem, TipoInstituicao, UserStatus
from app.models.geo import Instituicao, Ponto
from tests.factories.geo_factory import PontoFactory
from tests.factories.onibus_factory import OnibusFactory
from tests.factories.prefeitura_factory import PrefeituraFactory
from tests.factories.rota_factory import (
    DiasOperacaoFactory,
    HorarioRotaFactory,
    RotaAlunoFactory,
    RotaFactory,
    RotaPontoFactory,
)
from tests.factories.user_factory import AlunoFactory, GestorFactory, MotoristaFactory
from tests.factories.viagem_factory import AlunosConfirmadosFactory, ViagemFactory


class AuthenticatedClient:
    def __init__(self, flask_client, default_headers: dict[str, str]):
        self._client = flask_client
        self._default_headers = default_headers

    def _merge(self, headers: dict[str, str] | None):
        merged = dict(self._default_headers)
        if headers:
            merged.update(headers)
        return merged

    def get(self, *a, headers=None, **kw):
        return self._client.get(*a, headers=self._merge(headers), **kw)

    def post(self, *a, headers=None, **kw):
        return self._client.post(*a, headers=self._merge(headers), **kw)

    def put(self, *a, headers=None, **kw):
        return self._client.put(*a, headers=self._merge(headers), **kw)

    def patch(self, *a, headers=None, **kw):
        return self._client.patch(*a, headers=self._merge(headers), **kw)

    def delete(self, *a, headers=None, **kw):
        return self._client.delete(*a, headers=self._merge(headers), **kw)


@dataclass
class Actor:
    user: Any
    headers: dict[str, str]
    client: AuthenticatedClient


class QueryCounter:
    """Coleta as queries SQL emitidas dentro de um bloco.

    Existe para tornar N+1 uma asserção e não uma impressão. Um teste que
    afirma "esse endpoint faz 4 queries" falha quando alguém reintroduz o
    lazy load, e a mensagem de falha mostra o SQL repetido.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)

    def matching(self, fragment: str) -> list[str]:
        """Statements que contêm `fragment` (case-insensitive)."""
        needle = fragment.lower()
        return [s for s in self.statements if needle in s.lower()]

    def report(self) -> str:
        """SQL capturado, agrupado por statement idêntico e ordenado por repetição.

        O statement mais repetido é quase sempre o N+1.
        """
        if not self.statements:
            return "(nenhuma query capturada)"
        counts: dict[str, int] = {}
        for stmt in self.statements:
            normalised = " ".join(stmt.split())
            counts[normalised] = counts.get(normalised, 0) + 1
        lines = [f"{self.count} queries:"]
        for stmt, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {n:>3}x  {stmt[:160]}")
        return "\n".join(lines)

    def assert_at_most(self, expected: int) -> None:
        msg = f"esperava no máximo {expected} queries, saíram {self.count}\n{self.report()}"
        assert self.count <= expected, msg


@pytest.fixture()
def query_counter(_db):
    """Fábrica de context manager que conta queries num trecho específico.

    Escopo explícito de propósito: a montagem das fixtures também emite SQL,
    e contá-la junto tornaria os números inúteis.

        def test_agenda_nao_tem_n_mais_1(query_counter, aluno):
            with query_counter() as qc:
                resp = aluno.client.get("/api/v1/alunos/me/agenda")
            qc.assert_at_most(5)
    """

    @contextmanager
    def _counter() -> Iterator[QueryCounter]:
        counter = QueryCounter()
        engine = _db.engine

        def _on_execute(conn, cursor, statement, parameters, context, executemany):
            counter.statements.append(statement)

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            yield counter
        finally:
            # Remoção no finally: um listener vazado contaminaria todos os
            # testes seguintes da sessão, já que a engine é compartilhada.
            event.remove(engine, "before_cursor_execute", _on_execute)

    return _counter


# A suíte nunca deve iniciar o scheduler. A variável pode vazar do shell do dev.
os.environ.pop("RUN_SCHEDULER", None)

# Nome do banco que a suíte pode destruir. Todo teste roda contra Postgres real
# e o fixture `_db` faz `drop_all()` no fim de cada um.
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "buska_test")

# O alvo precisa ser definido antes de `create_app()`. O Flask-SQLAlchemy lê a
# URI dentro de `init_app()`, então um `config.update()` depois da criação do
# app não religa a engine: escreve no config e a conexão continua na URI antiga.
# `load_dotenv()` não sobrescreve variável já presente no ambiente, então esta
# linha vence o `DB_NAME` do `.env`.
os.environ["DB_NAME"] = TEST_DB_NAME


def _exigir_banco_de_teste(engine) -> None:
    """Aborta a suíte se o alvo real da engine não for um banco de teste.

    Guarda contra a regressão que apagava o banco de desenvolvimento: o alvo
    verificado é `engine.url`, não o `app.config`, porque foi exatamente a
    divergência entre os dois que passou despercebida.
    """
    nome = engine.url.database or ""
    if nome != TEST_DB_NAME:
        raise RuntimeError(
            f"A suíte está prestes a rodar create_all/drop_all em {nome!r}, "
            f"que não é o banco de teste ({TEST_DB_NAME!r}). Alvo real da engine: "
            f"{engine.url.render_as_string(hide_password=True)}. Abortando."
        )


@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        DEBUG=True,
        JWT_SECRET_KEY="change_this_secret_key_use_long_random_string",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    return app


@pytest.fixture()
def _db(app):
    with app.app_context():
        _exigir_banco_de_teste(db.engine)
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app, _db):
    return app.test_client()


@pytest.fixture()
def prefeitura(_db):
    p = PrefeituraFactory()
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture()
def other_prefeitura(_db):
    p = PrefeituraFactory()
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture()
def gestor(client, app, _db, prefeitura):
    u = GestorFactory(prefeitura_id=prefeitura.id)
    _db.session.add(u)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(u.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=u, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def other_gestor(client, app, _db, other_prefeitura):
    u = GestorFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(u)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(u.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=u, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def aluno(client, app, _db, prefeitura):
    u = AlunoFactory(prefeitura_id=prefeitura.id)
    _db.session.add(u)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(u.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=u, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def ponto_instituicao(_db, prefeitura):
    p = Ponto(prefeitura_id=prefeitura.id, latitude=-7.3, longitude=-35.7, apelido="Escola")
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture()
def aluno_com_instituicao(_db, prefeitura, aluno, ponto_instituicao):
    """O mesmo `aluno`, agora estudando numa instituição que tem ponto de parada."""
    inst = Instituicao(
        fonte="MANUAL",
        codigo_externo="INST-CONFTEST",
        nome="Escola Conftest",
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        uf="PB",
        prefeitura_id=prefeitura.id,
        ponto_id=ponto_instituicao.id,
    )
    _db.session.add(inst)
    _db.session.flush()
    aluno.user.instituicao_id = inst.id
    _db.session.commit()
    return aluno


@pytest.fixture()
def aluno_pending(client, app, _db, prefeitura):
    u = AlunoFactory(prefeitura_id=prefeitura.id)
    u.status = UserStatus.PENDING_SIGNUP
    u.signup_completed_at = None
    _db.session.add(u)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(u.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=u, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def other_aluno(client, app, _db, other_prefeitura):
    u = AlunoFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(u)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(u.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=u, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def ponto(_db, prefeitura):
    p = PontoFactory(prefeitura_id=prefeitura.id)
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture()
def motorista(client, app, _db, prefeitura):
    m = MotoristaFactory(prefeitura_id=prefeitura.id)
    _db.session.add(m)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(m.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=m, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def other_motorista(client, app, _db, other_prefeitura):
    m = MotoristaFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(m)
    _db.session.commit()

    with app.app_context():
        token = create_access_token(identity=str(m.id))

    headers = {"Authorization": f"Bearer {token}"}
    return Actor(user=m, headers=headers, client=AuthenticatedClient(client, headers))


@pytest.fixture()
def onibus(_db, prefeitura):
    o = OnibusFactory(prefeitura_id=prefeitura.id)
    _db.session.add(o)
    _db.session.commit()
    return o


@pytest.fixture()
def rota(_db, prefeitura, motorista, onibus):
    r = RotaFactory(
        prefeitura_id=prefeitura.id,
        motorista_padrao_id=motorista.user.id,
        veiculo_padrao_id=onibus.id,
    )
    _db.session.add(r)
    _db.session.commit()
    return r


@pytest.fixture()
def horario_rota(_db, rota):
    h = HorarioRotaFactory(rota_id=rota.id, sentido=SentidoViagem.IDA)
    _db.session.add(h)
    _db.session.commit()
    return h


@pytest.fixture()
def dia_operacao(_db, horario_rota):
    d = DiasOperacaoFactory(horario_rota_id=horario_rota.id, dia=DiaDaSemana.SEG)
    _db.session.add(d)
    _db.session.commit()
    return d


@pytest.fixture()
def dia_operacao_quarta(_db, horario_rota):
    d = DiasOperacaoFactory(horario_rota_id=horario_rota.id, dia=DiaDaSemana.QUA)
    _db.session.add(d)
    _db.session.commit()
    return d


@pytest.fixture()
def rota_ponto(_db, rota, ponto):
    rp = RotaPontoFactory(rota_id=rota.id, ponto_id=ponto.id, ordem=1)
    _db.session.add(rp)
    _db.session.commit()
    return rp


@pytest.fixture()
def rota_aluno(_db, rota, aluno):
    ra = RotaAlunoFactory(rota_id=rota.id, aluno_id=aluno.user.id)
    _db.session.add(ra)
    _db.session.commit()
    return ra


@pytest.fixture()
def viagem_futura_agendada_com_motorista(_db, horario_rota, motorista):
    v = ViagemFactory(
        horario_rota_id=horario_rota.id,
        data=date.today() + timedelta(days=7),
        status=StatusViagem.AGENDADA,
        motorista_id=motorista.user.id,
    )
    _db.session.add(v)
    _db.session.commit()
    return v


@pytest.fixture()
def viagem_futura_iniciada_com_motorista(_db, horario_rota, motorista):
    v = ViagemFactory(
        horario_rota_id=horario_rota.id,
        data=date.today() + timedelta(days=7),
        status=StatusViagem.EM_ANDAMENTO,
        motorista_id=motorista.user.id,
        inicio_real=datetime.now(UTC),
    )
    _db.session.add(v)
    _db.session.commit()
    return v


@pytest.fixture()
def confirmacao_aluno(_db, viagem_futura_agendada_com_motorista, aluno, ponto):
    conf = AlunosConfirmadosFactory(
        viagem_id=viagem_futura_agendada_com_motorista.id,
        aluno_id=aluno.user.id,
        confirmacao=False,
        ponto_embarque_id=None,
        ponto_destino_id=None,
    )
    _db.session.add(conf)
    _db.session.commit()
    return conf
