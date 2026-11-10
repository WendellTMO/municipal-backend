"""GET /viagens/minhas (motorista) com periodo, limit, offset e viagem_id."""

from datetime import date, timedelta

import pytest

from app.models.enum import StatusViagem
from tests.factories.viagem_factory import ViagemFactory

pytestmark = pytest.mark.integration

URL = "/v1/viagens/minhas"


def _viagem(_db, horario_rota, motorista, dias, status):
    v = ViagemFactory(
        horario_rota_id=horario_rota.id,
        data=date.today() + timedelta(days=dias),
        status=status,
        motorista_id=motorista.user.id,
    )
    _db.session.add(v)
    _db.session.commit()
    return v


@pytest.fixture()
def viagens(_db, horario_rota, motorista):
    return {
        "antiga_feita": _viagem(_db, horario_rota, motorista, -10, StatusViagem.FINALIZADA),
        "antiga_perdida": _viagem(_db, horario_rota, motorista, -5, StatusViagem.AGENDADA),
        "ontem_aberta": _viagem(_db, horario_rota, motorista, -1, StatusViagem.AGENDADA),
        "hoje": _viagem(_db, horario_rota, motorista, 0, StatusViagem.AGENDADA),
        "amanha": _viagem(_db, horario_rota, motorista, 1, StatusViagem.AGENDADA),
        "cancelada_futura": _viagem(_db, horario_rota, motorista, 3, StatusViagem.CANCELADA),
    }


def _ids(resp):
    return [item["id"] for item in resp.get_json()["items"]]


def test_proximas_vem_da_mais_perto_para_a_mais_longe(motorista, viagens):
    resp = motorista.client.get(f"{URL}?periodo=proximas")

    assert resp.status_code == 200
    esperado = [viagens[k].id for k in ("ontem_aberta", "hoje", "amanha", "cancelada_futura")]
    assert _ids(resp) == [str(i) for i in esperado]


def test_historico_vem_do_mais_recente_para_o_mais_antigo(motorista, viagens):
    resp = motorista.client.get(f"{URL}?periodo=historico")

    # A de ontem ainda aberta aparece nas duas listas: o app decide se vira "não realizada".
    chaves = ("cancelada_futura", "ontem_aberta", "antiga_perdida", "antiga_feita")
    esperado = [viagens[k].id for k in chaves]
    assert _ids(resp) == [str(i) for i in esperado]


def test_em_andamento_sempre_entra_nas_proximas(_db, horario_rota, motorista):
    antiga = _viagem(_db, horario_rota, motorista, -4, StatusViagem.EM_ANDAMENTO)

    resp = motorista.client.get(f"{URL}?periodo=proximas")

    assert _ids(resp) == [str(antiga.id)]


def test_limit_e_offset_paginam_sem_repetir(motorista, viagens):
    todas = _ids(motorista.client.get(URL))

    primeira = _ids(motorista.client.get(f"{URL}?limit=4"))
    segunda = _ids(motorista.client.get(f"{URL}?limit=4&offset=4"))

    assert len(todas) == 6
    assert primeira == todas[:4]
    assert segunda == todas[4:]


def test_viagem_id_devolve_so_a_viagem(motorista, viagens):
    alvo = viagens["hoje"]

    resp = motorista.client.get(f"{URL}?viagem_id={alvo.id}")

    assert _ids(resp) == [str(alvo.id)]


def test_nao_enxerga_viagem_de_outro_motorista(other_motorista, viagens):
    assert _ids(other_motorista.client.get(URL)) == []
    resp = other_motorista.client.get(f"{URL}?viagem_id={viagens['hoje'].id}")
    assert _ids(resp) == []


@pytest.mark.parametrize(
    "consulta", ["limit=0", "limit=101", "offset=-1", "periodo=tudo", "viagem_id=abc"]
)
def test_parametros_invalidos_sao_recusados(motorista, consulta):
    assert motorista.client.get(f"{URL}?{consulta}").status_code == 400
