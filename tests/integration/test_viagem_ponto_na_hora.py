from app.models.geo import Ponto
from app.models.rota import RotaPonto
from app.models.viagem import ViagemPonto
from tests.factories.geo_factory import PontoFactory
from tests.factories.user_factory import MotoristaFactory


def _paradas(_db, viagem, prefeitura, visitados):
    """Cria 3 paradas (ordem 1..3); `visitados` diz quantas das primeiras já foram visitadas."""
    pontos = []
    for i in range(3):
        p = PontoFactory(prefeitura_id=prefeitura.id, apelido=f"P{i + 1}")
        _db.session.add(p)
        _db.session.flush()
        _db.session.add(
            ViagemPonto(viagem_id=viagem.id, ponto_id=p.id, ordem=i + 1, visitado=i < visitados)
        )
        pontos.append(p)
    _db.session.commit()
    return pontos


def _url(viagem):
    return f"/v1/viagens/{viagem.id}/pontos"


def _apelidos(resp):
    paradas = sorted(resp.get_json()["pontos"], key=lambda p: p["ordem"])
    return [(p["apelido"], p["ordem"]) for p in paradas]


def test_proxima_entra_depois_da_ultima_visitada_e_renumera(
    _db, motorista, prefeitura, ponto, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    _paradas(_db, v, prefeitura, visitados=1)
    ponto.apelido = "NOVO"
    _db.session.commit()

    r = motorista.client.post(_url(v), json={"ponto_id": str(ponto.id)})

    assert r.status_code == 201
    assert _apelidos(r) == [("P1", 1), ("NOVO", 2), ("P2", 3), ("P3", 4)]
    paradas = r.get_json()["pontos"]
    assert all("latitude" in p and "longitude" in p for p in paradas)


def test_fim_entra_no_final(
    _db, motorista, prefeitura, ponto, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    _paradas(_db, v, prefeitura, visitados=1)
    ponto.apelido = "NOVO"
    _db.session.commit()

    r = motorista.client.post(_url(v), json={"ponto_id": str(ponto.id), "posicao": "fim"})

    assert r.status_code == 201
    assert _apelidos(r) == [("P1", 1), ("P2", 2), ("P3", 3), ("NOVO", 4)]


def test_ponto_novo_por_coordenadas(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista

    r = motorista.client.post(
        _url(v), json={"apelido": "Esquina", "latitude": -7.23, "longitude": -35.88}
    )

    assert r.status_code == 201
    assert _apelidos(r) == [("Esquina", 1)]
    criado = Ponto.query.filter_by(apelido="Esquina").one()
    assert criado.prefeitura_id == prefeitura.id
    assert float(criado.latitude) == -7.23


def test_rota_nao_muda(
    _db, motorista, rota, rota_ponto, ponto, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista

    r = motorista.client.post(_url(v), json={"latitude": -7.2, "longitude": -35.9})

    assert r.status_code == 201
    pontos_da_rota = RotaPonto.query.filter_by(rota_id=rota.id).all()
    assert [rp.ponto_id for rp in pontos_da_rota] == [ponto.id]


def test_outro_motorista_da_mesma_prefeitura_403(
    _db, prefeitura, client, viagem_futura_iniciada_com_motorista, app
):
    from flask_jwt_extended import create_access_token

    outro = MotoristaFactory(prefeitura_id=prefeitura.id)
    _db.session.add(outro)
    _db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(outro.id))

    r = client.post(
        _url(viagem_futura_iniciada_com_motorista),
        json={"latitude": -7.2, "longitude": -35.9},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 403


def test_aluno_403(aluno, viagem_futura_iniciada_com_motorista):
    r = aluno.client.post(
        _url(viagem_futura_iniciada_com_motorista), json={"latitude": -7.2, "longitude": -35.9}
    )
    assert r.status_code == 403


def test_viagem_de_outra_prefeitura_404(other_motorista, viagem_futura_iniciada_com_motorista):
    r = other_motorista.client.post(
        _url(viagem_futura_iniciada_com_motorista), json={"latitude": -7.2, "longitude": -35.9}
    )
    assert r.status_code == 404


def test_viagem_nao_em_andamento_recusa(motorista, viagem_futura_agendada_com_motorista):
    r = motorista.client.post(
        _url(viagem_futura_agendada_com_motorista), json={"latitude": -7.2, "longitude": -35.9}
    )
    assert r.status_code == 400


def test_ponto_de_outra_prefeitura_404(
    _db, motorista, other_prefeitura, viagem_futura_iniciada_com_motorista
):
    estranho = PontoFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(estranho)
    _db.session.commit()

    r = motorista.client.post(
        _url(viagem_futura_iniciada_com_motorista), json={"ponto_id": str(estranho.id)}
    )

    assert r.status_code == 404


def test_coordenadas_invalidas_400(motorista, viagem_futura_iniciada_com_motorista):
    url = _url(viagem_futura_iniciada_com_motorista)
    corpos = [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": 0},
        {},
        {"apelido": "x" * 101, "latitude": 0, "longitude": 0},
        {"latitude": 0, "longitude": 0, "posicao": "meio"},
    ]
    for corpo in corpos:
        assert motorista.client.post(url, json=corpo).status_code == 400, corpo


def test_ponto_duplicado_409(motorista, ponto, viagem_futura_iniciada_com_motorista):
    url = _url(viagem_futura_iniciada_com_motorista)
    assert motorista.client.post(url, json={"ponto_id": str(ponto.id)}).status_code == 201
    assert motorista.client.post(url, json={"ponto_id": str(ponto.id)}).status_code == 409
