"""PUT /alunos/me e leitura do endereço de moradia (Endereco.aluno_id)."""

import pytest

from app.models.enum import UserStatus
from app.models.geo import Endereco
from tests.factories.user_factory import AlunoFactory

pytestmark = pytest.mark.integration

ENDERECO = {
    "logradouro": "Rua das Flores",
    "numero": "120",
    "bairro": "Centro",
    "cidade": "Campina Grande",
    "estado": "pb",
    "cep": "58400000",
    "complemento": "Apto 2",
}
CHAVES = {"logradouro", "numero", "bairro", "cidade", "estado", "cep", "complemento"}


@pytest.fixture()
def aluno(_db, aluno):
    """A fixture base nasce PENDING_SIGNUP, que exige cadastro completo no PUT."""
    aluno.user.status = UserStatus.ACTIVE
    _db.session.commit()
    return aluno


def _enderecos_do_aluno(aluno):
    return Endereco.query.filter_by(aluno_id=aluno.id).all()


def test_put_sem_endereco_nao_estoura_e_nao_muda_nada(_db, aluno):
    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    resp = aluno.client.put("/v1/alunos/me", json={"nome": "Novo Nome"})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["nome"] == "Novo Nome"
    assert resp.get_json()["endereco"]["logradouro"] == "Rua das Flores"
    assert len(_enderecos_do_aluno(aluno.user)) == 1


def test_put_com_endereco_null_nao_estoura(_db, aluno):
    resp = aluno.client.put("/v1/alunos/me", json={"endereco": None, "endereco_casa": None})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["endereco"] is None


def test_put_com_endereco_cria_quando_nao_existe(_db, aluno):
    resp = aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    corpo = resp.get_json()["endereco"]
    assert set(corpo) == CHAVES
    assert corpo["estado"] == "PB"
    assert len(_enderecos_do_aluno(aluno.user)) == 1


def test_put_com_endereco_atualiza_o_existente(_db, aluno):
    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    novo = dict(ENDERECO, logradouro="Rua Nova", complemento=None)
    resp = aluno.client.put("/v1/alunos/me", json={"endereco": novo})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["endereco"]["logradouro"] == "Rua Nova"
    assert resp.get_json()["endereco"]["complemento"] is None
    assert len(_enderecos_do_aluno(aluno.user)) == 1


def test_get_alunos_me_devolve_o_endereco(_db, aluno):
    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    resp = aluno.client.get("/v1/alunos/me")

    assert resp.status_code == 200
    assert set(resp.get_json()["endereco"]) == CHAVES
    assert resp.get_json()["endereco"]["estado"] == "PB"


def test_get_alunos_me_sem_endereco_devolve_null(_db, aluno):
    resp = aluno.client.get("/v1/alunos/me")

    assert resp.status_code == 200
    assert resp.get_json()["endereco"] is None


def test_get_users_me_devolve_o_endereco(_db, aluno):
    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    resp = aluno.client.get("/v1/users/me")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["endereco"]["cidade"] == "Campina Grande"
    assert set(resp.get_json()["endereco"]) == CHAVES


def test_get_users_me_sem_endereco_devolve_null(_db, aluno):
    resp = aluno.client.get("/v1/users/me")

    assert resp.get_json()["endereco"] is None


def test_outro_aluno_nao_le_o_endereco(_db, aluno, prefeitura, client, app):
    from flask_jwt_extended import create_access_token

    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})
    outro = AlunoFactory(prefeitura_id=prefeitura.id)
    _db.session.add(outro)
    _db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(outro.id))

    resp = client.get(f"/v1/users/{aluno.user.id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 403
    assert "Rua das Flores" not in resp.get_data(as_text=True)


def test_gestor_da_mesma_prefeitura_le_o_endereco(_db, aluno, gestor):
    aluno.client.put("/v1/alunos/me", json={"endereco": ENDERECO})

    resp = gestor.client.get(f"/v1/users/{aluno.user.id}")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["endereco"]["logradouro"] == "Rua das Flores"
