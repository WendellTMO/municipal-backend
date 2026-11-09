"""GET /viagens/aluno/agenda com limit, offset e rota_id (todos opcionais)."""

from datetime import date, timedelta

import pytest

from app.models.enum import StatusViagem
from tests.factories.viagem_factory import ViagemFactory

pytestmark = pytest.mark.integration

URL = "/v1/viagens/aluno/agenda"


@pytest.fixture()
def cinco_viagens(_db, horario_rota, motorista, rota_aluno):
    viagens = []
    for dias in range(1, 6):
        v = ViagemFactory(
            horario_rota_id=horario_rota.id,
            data=date.today() + timedelta(days=dias),
            status=StatusViagem.AGENDADA,
            motorista_id=motorista.user.id,
        )
        _db.session.add(v)
        viagens.append(v)
    _db.session.commit()
    return viagens


def _datas(resp):
    return [item["data"] for item in resp.get_json()["items"]]


def test_sem_parametros_devolve_tudo(aluno, cinco_viagens):
    resp = aluno.client.get(URL)

    assert resp.status_code == 200
    assert len(_datas(resp)) == 5


def test_limit_e_offset_paginam_na_ordem_da_data(aluno, cinco_viagens):
    todas = _datas(aluno.client.get(URL))

    primeira = _datas(aluno.client.get(f"{URL}?limit=2"))
    segunda = _datas(aluno.client.get(f"{URL}?limit=2&offset=2"))
    ultima = _datas(aluno.client.get(f"{URL}?limit=2&offset=4"))

    assert primeira == todas[0:2]
    assert segunda == todas[2:4]
    assert ultima == todas[4:5]


def test_filtra_por_rota(aluno, cinco_viagens, rota):
    com_rota = aluno.client.get(f"{URL}?rota_id={rota.id}")
    outra_rota = aluno.client.get(f"{URL}?rota_id=00000000-0000-0000-0000-000000000001")

    assert len(_datas(com_rota)) == 5
    assert _datas(outra_rota) == []


def test_total_de_alunos_da_rota_vem_no_item(aluno, cinco_viagens):
    item = aluno.client.get(URL).get_json()["items"][0]

    assert item["total_alunos"] == 1


@pytest.mark.parametrize("consulta", ["limit=0", "limit=101", "offset=-1", "rota_id=abc"])
def test_parametros_invalidos_sao_recusados(aluno, consulta):
    resp = aluno.client.get(f"{URL}?{consulta}")

    assert resp.status_code == 400


def test_numero_de_consultas_nao_cresce_com_as_viagens(_db, aluno, cinco_viagens):
    from sqlalchemy import event

    def contar(consulta: str) -> int:
        comandos: list[str] = []

        def anotar(conexao, cursor, statement, *resto):
            comandos.append(statement)

        event.listen(_db.engine, "before_cursor_execute", anotar)
        try:
            aluno.client.get(consulta)
        finally:
            event.remove(_db.engine, "before_cursor_execute", anotar)
        return len(comandos)

    aluno.client.get(URL)  # aquecimento: a primeira chamada faz consultas que as outras não fazem
    com_uma = contar(f"{URL}?limit=1")
    com_cinco = contar(URL)

    assert com_cinco == com_uma
