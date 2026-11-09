"""PUT /alunos/me com `instituicao_ids`: várias instituições por aluno."""

import pytest

from app.models.enum import UserStatus
from app.models.geo import Instituicao, TipoInstituicao

pytestmark = pytest.mark.integration


def _nova_instituicao(_db, prefeitura, codigo, nome):
    inst = Instituicao(
        fonte="MANUAL",
        codigo_externo=codigo,
        nome=nome,
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        uf="PB",
        prefeitura_id=prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


@pytest.fixture()
def aluno_ativo(_db, aluno):
    aluno.user.status = UserStatus.ACTIVE
    _db.session.commit()
    return aluno


def test_varias_instituicoes_primeira_vira_principal(_db, prefeitura, aluno_ativo):
    a = _nova_instituicao(_db, prefeitura, "A", "Escola A")
    b = _nova_instituicao(_db, prefeitura, "B", "Escola B")

    resp = aluno_ativo.client.put(
        "/v1/alunos/me", json={"instituicao_ids": [str(a.id), str(b.id)]}
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    corpo = resp.get_json()
    assert corpo["instituicao_id"] == str(a.id)
    assert [i["nome"] for i in corpo["instituicoes"]] == ["Escola A", "Escola B"]


def test_remover_extra_e_repetidas(_db, prefeitura, aluno_ativo):
    a = _nova_instituicao(_db, prefeitura, "A", "Escola A")
    b = _nova_instituicao(_db, prefeitura, "B", "Escola B")
    aluno_ativo.client.put("/v1/alunos/me", json={"instituicao_ids": [str(a.id), str(b.id)]})

    resp = aluno_ativo.client.put(
        "/v1/alunos/me", json={"instituicao_ids": [str(b.id), str(b.id)]}
    )

    corpo = resp.get_json()
    assert corpo["instituicao_id"] == str(b.id)
    assert [i["nome"] for i in corpo["instituicoes"]] == ["Escola B"]


def test_instituicao_de_outra_prefeitura_e_recusada(_db, other_prefeitura, aluno_ativo):
    fora = _nova_instituicao(_db, other_prefeitura, "X", "Escola X")

    resp = aluno_ativo.client.put("/v1/alunos/me", json={"instituicao_ids": [str(fora.id)]})

    assert resp.status_code == 400


def test_lista_vazia_e_recusada(aluno_ativo):
    resp = aluno_ativo.client.put("/v1/alunos/me", json={"instituicao_ids": []})

    assert resp.status_code == 400
