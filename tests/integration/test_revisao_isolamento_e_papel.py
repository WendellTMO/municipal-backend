"""Achados da revisão: papel na lista de motoristas e motorista ou ônibus de outra prefeitura."""

from app.models.rota import Rota
from tests.factories.onibus_factory import OnibusFactory


def test_aluno_nao_lista_motoristas(aluno, motorista):
    resposta = aluno.client.get("/v1/users/motoristas")

    assert resposta.status_code == 403


def test_motorista_nao_lista_motoristas(motorista):
    resposta = motorista.client.get("/v1/users/motoristas")

    assert resposta.status_code == 403


def test_gestor_lista_so_os_motoristas_da_propria_prefeitura(gestor, motorista, other_motorista):
    resposta = gestor.client.get("/v1/users/motoristas")

    assert resposta.status_code == 200
    ids = [m["id"] for m in resposta.get_json()["items"]]
    assert str(motorista.user.id) in ids
    assert str(other_motorista.user.id) not in ids


def test_create_rota_recusa_motorista_de_outra_prefeitura(gestor, other_motorista, _db):
    resposta = gestor.client.post(
        "/v1/rotas/",
        json={
            "nome": "Rota com motorista alheio",
            "motorista_padrao_id": str(other_motorista.user.id),
        },
    )

    assert resposta.status_code == 404
    assert Rota.query.filter_by(nome="Rota com motorista alheio").count() == 0


def test_create_rota_recusa_onibus_de_outra_prefeitura(gestor, other_prefeitura, _db):
    onibus_alheio = OnibusFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(onibus_alheio)
    _db.session.commit()

    resposta = gestor.client.post(
        "/v1/rotas/",
        json={"nome": "Rota com onibus alheio", "veiculo_padrao_id": str(onibus_alheio.id)},
    )

    assert resposta.status_code == 404
    assert Rota.query.filter_by(nome="Rota com onibus alheio").count() == 0


def test_create_rota_aceita_motorista_e_onibus_da_propria_prefeitura(gestor, motorista, onibus):
    """Controle: a guarda nova não pode derrubar o caminho legítimo."""
    resposta = gestor.client.post(
        "/v1/rotas/",
        json={
            "nome": "Rota legitima",
            "motorista_padrao_id": str(motorista.user.id),
            "veiculo_padrao_id": str(onibus.id),
        },
    )

    assert resposta.status_code in (200, 201), resposta.get_data(as_text=True)


def test_update_rota_recusa_motorista_de_outra_prefeitura(gestor, rota, other_motorista):
    resposta = gestor.client.put(
        f"/v1/rotas/{rota.id}", json={"motorista_padrao_id": str(other_motorista.user.id)}
    )

    assert resposta.status_code == 404
