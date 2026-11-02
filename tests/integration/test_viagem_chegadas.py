from datetime import UTC, datetime, timedelta

from app.models.enum import StatusViagem
from app.models.notificacao import Notificacao
from app.models.viagem import AlunosConfirmados, ViagemPonto
from tests.factories.geo_factory import PontoFactory

# Dois pontos a cerca de 1 km um do outro.
LAT, LON = -7.2300, -35.8800


def _url(viagem):
    return f"/v1/viagens/{viagem.id}/pontos-visitados"


def _paradas(_db, viagem, prefeitura, quantidade=3):
    pontos = []
    for i in range(quantidade):
        p = PontoFactory(
            prefeitura_id=prefeitura.id, apelido=f"P{i + 1}", latitude=LAT + i * 0.01, longitude=LON
        )
        _db.session.add(p)
        _db.session.flush()
        _db.session.add(ViagemPonto(viagem_id=viagem.id, ponto_id=p.id, ordem=i + 1))
        pontos.append(p)
    _db.session.commit()
    return pontos


def _evento(ponto, minutos_atras=0, origem="manual", **extra):
    hora = datetime.now(UTC) - timedelta(minutes=minutos_atras)
    evento = {"ponto_id": str(ponto.id), "detectado_em": hora.isoformat(), "origem": origem}
    evento.update(extra)
    return evento


def _parada(_db, viagem, ponto):
    return _db.session.get(ViagemPonto, (viagem.id, ponto.id))


def test_chegada_auto_perto_do_ponto_marca_visitado(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, _, _ = _paradas(_db, v, prefeitura)

    r = motorista.client.post(
        _url(v),
        json={"eventos": [_evento(p1, origem="auto", latitude=float(p1.latitude), longitude=LON)]},
    )

    assert r.status_code == 200
    assert r.get_json() == {"aceitos": [str(p1.id)], "rejeitados": []}
    parada = _parada(_db, v, p1)
    assert parada.visitado is True
    assert parada.chegada_real is not None
    assert parada.origem_chegada == "auto"


def test_ordem_diferente_da_lista_e_aceita(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, p2, p3 = _paradas(_db, v, prefeitura)

    r = motorista.client.post(_url(v), json={"eventos": [_evento(p3), _evento(p1)]})

    assert r.status_code == 200
    assert len(r.get_json()["aceitos"]) == 2
    assert _parada(_db, v, p3).visitado is True
    assert _parada(_db, v, p1).visitado is True
    assert not _parada(_db, v, p2).visitado


def test_repetir_evento_nao_duplica_e_vale_a_chegada_mais_antiga(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, _, _ = _paradas(_db, v, prefeitura)

    motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=2)]})
    primeira = _parada(_db, v, p1).chegada_real
    r = motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=0)]})
    assert r.get_json()["aceitos"] == [str(p1.id)]
    _db.session.refresh(_parada(_db, v, p1))
    assert _parada(_db, v, p1).chegada_real == primeira

    motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=5)]})
    _db.session.refresh(_parada(_db, v, p1))
    assert _parada(_db, v, p1).chegada_real < primeira


def test_rejeita_ponto_de_fora_futuro_e_auto_longe(
    _db, motorista, prefeitura, ponto, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, p2, p3 = _paradas(_db, v, prefeitura)
    eventos = [
        _evento(ponto),
        _evento(p1, minutos_atras=-30),
        _evento(p2, origem="auto", latitude=LAT + 0.5, longitude=LON),
        _evento(p3, origem="auto"),
    ]

    r = motorista.client.post(_url(v), json={"eventos": eventos})

    assert r.status_code == 200
    motivos = {x["ponto_id"]: x["motivo"] for x in r.get_json()["rejeitados"]}
    assert motivos == {
        str(ponto.id): "ponto_fora_da_viagem",
        str(p1.id): "horario_no_futuro",
        str(p2.id): "longe_do_ponto",
        str(p3.id): "sem_posicao",
    }
    assert r.get_json()["aceitos"] == []
    assert not _parada(_db, v, p1).visitado


def test_viagem_finalizada_ainda_recebe_a_fila(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    v.status = StatusViagem.FINALIZADA
    _db.session.commit()
    p1, _, _ = _paradas(_db, v, prefeitura)

    r = motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=3)]})

    assert r.status_code == 200
    assert r.get_json()["aceitos"] == [str(p1.id)]


def test_viagem_agendada_nao_recebe(
    _db, motorista, prefeitura, viagem_futura_agendada_com_motorista
):
    v = viagem_futura_agendada_com_motorista
    p1, _, _ = _paradas(_db, v, prefeitura)

    r = motorista.client.post(_url(v), json={"eventos": [_evento(p1)]})

    assert r.status_code == 400


def test_so_o_motorista_da_viagem(
    _db, aluno, other_motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, _, _ = _paradas(_db, v, prefeitura)
    corpo = {"eventos": [_evento(p1)]}

    assert aluno.client.post(_url(v), json=corpo).status_code == 403
    assert other_motorista.client.post(_url(v), json=corpo).status_code == 404


def test_lote_vazio_e_invalido(_db, motorista, viagem_futura_iniciada_com_motorista):
    r = motorista.client.post(_url(viagem_futura_iniciada_com_motorista), json={"eventos": []})

    assert r.status_code == 400


def _aluno_esperando(_db, viagem, aluno, ponto):
    _db.session.add(
        AlunosConfirmados(
            viagem_id=viagem.id,
            aluno_id=aluno.user.id,
            confirmacao=True,
            ponto_embarque_id=ponto.id,
        )
    )
    _db.session.commit()


def _avisos(_db, aluno):
    return Notificacao.query.filter_by(usuario_id=aluno.user.id).count()


def test_avisa_o_aluno_do_ponto_so_quando_a_chegada_e_recente(
    _db, motorista, aluno, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, p2, _ = _paradas(_db, v, prefeitura)
    _aluno_esperando(_db, v, aluno, p1)

    motorista.client.post(_url(v), json={"eventos": [_evento(p2)]})
    assert _avisos(_db, aluno) == 0

    motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=1)]})
    assert _avisos(_db, aluno) == 1

    motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=1)]})
    assert _avisos(_db, aluno) == 1


def test_chegada_antiga_e_conferencia_nao_avisam(
    _db, motorista, aluno, prefeitura, viagem_futura_iniciada_com_motorista
):
    v = viagem_futura_iniciada_com_motorista
    p1, p2, _ = _paradas(_db, v, prefeitura)
    _aluno_esperando(_db, v, aluno, p1)

    motorista.client.post(_url(v), json={"eventos": [_evento(p1, minutos_atras=30)]})
    assert _avisos(_db, aluno) == 0

    # O mesmo aluno passa a esperar no p2: a chegada por conferência também não avisa.
    conf = _db.session.get(AlunosConfirmados, (v.id, aluno.user.id))
    conf.ponto_embarque_id = p2.id
    _db.session.commit()
    motorista.client.post(_url(v), json={"eventos": [_evento(p2, origem="conferencia")]})
    assert _avisos(_db, aluno) == 0
