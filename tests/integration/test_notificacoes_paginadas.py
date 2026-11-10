"""GET /notificacoes paginado e GET /notificacoes/nao-lidas."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.notificacao import Notificacao

pytestmark = pytest.mark.integration

URL = "/v1/notificacoes/"


@pytest.fixture()
def quarenta(_db, aluno):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(40):
        _db.session.add(
            Notificacao(
                usuario_id=aluno.user.id,
                titulo=f"Aviso {i}",
                mensagem="texto",
                enviada=i < 10,
                created_at=base + timedelta(minutes=i),
            )
        )
    _db.session.commit()


def _titulos(resp):
    return [n["titulo"] for n in resp.get_json()]


def test_padrao_devolve_os_30_mais_novos(aluno, quarenta):
    resp = aluno.client.get(URL)

    assert resp.status_code == 200
    titulos = _titulos(resp)
    assert len(titulos) == 30
    assert titulos[0] == "Aviso 39"
    assert titulos[-1] == "Aviso 10"


def test_limit_e_offset_paginam_sem_repetir(aluno, quarenta):
    primeira = _titulos(aluno.client.get(f"{URL}?limit=15"))
    segunda = _titulos(aluno.client.get(f"{URL}?limit=15&offset=15"))
    terceira = _titulos(aluno.client.get(f"{URL}?limit=15&offset=30"))

    assert len(primeira) == 15 and len(segunda) == 15 and len(terceira) == 10
    assert len(set(primeira + segunda + terceira)) == 40


def test_conta_so_as_nao_lidas(aluno, quarenta):
    resp = aluno.client.get("/v1/notificacoes/nao-lidas")

    assert resp.status_code == 200
    assert resp.get_json() == {"count": 30}


def test_filtra_por_estado(aluno, quarenta):
    nao_lidas = aluno.client.get(f"{URL}?estado=nao_lidas&limit=100").get_json()
    lidas = aluno.client.get(f"{URL}?estado=lidas&limit=100").get_json()

    assert len(nao_lidas) == 30 and all(not n["enviada"] for n in nao_lidas)
    assert len(lidas) == 10 and all(n["enviada"] for n in lidas)


def test_filtro_nao_mostra_notificacao_de_outro_usuario(_db, aluno, other_aluno, quarenta):
    _db.session.add(
        Notificacao(usuario_id=other_aluno.user.id, titulo="Do outro", mensagem="x", enviada=False)
    )
    _db.session.commit()

    titulos = _titulos(aluno.client.get(f"{URL}?estado=nao_lidas&limit=100"))

    assert "Do outro" not in titulos


@pytest.mark.parametrize("consulta", ["limit=0", "limit=101", "offset=-1", "estado=tudo"])
def test_parametros_invalidos_sao_recusados(aluno, consulta):
    assert aluno.client.get(f"{URL}?{consulta}").status_code == 400
