from datetime import time as hora

from app.models.base import db
from app.models.rota import HorarioRota
from app.models.viagem import Viagem, ViagemPonto
from app.services import rotas_service
from tests.factories.geo_factory import PontoFactory

TODOS_OS_DIAS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]


def _rota_com_ponto_de_ida_e_de_volta(gestor, prefeitura):
    bairro = PontoFactory(prefeitura_id=prefeitura.id, apelido="Bairro")
    escola = PontoFactory(prefeitura_id=prefeitura.id, apelido="Escola")
    volta = PontoFactory(prefeitura_id=prefeitura.id, apelido="Bairro (volta)")
    db.session.add_all([bairro, escola, volta])
    db.session.commit()
    rota = rotas_service.create_rota(
        str(gestor.user.id),
        {
            "nome": "Rota com sentido",
            "pontos": [
                {"ponto_id": str(bairro.id), "ordem": 1, "sentido": "IDA"},
                {"ponto_id": str(escola.id), "ordem": 2},
                {"ponto_id": str(volta.id), "ordem": 3, "sentido": "VOLTA"},
            ],
            "horarios": [
                {"horario_saida": hora(5, 0), "sentido": "IDA", "dias": TODOS_OS_DIAS},
                {"horario_saida": hora(12, 0), "sentido": "VOLTA", "dias": TODOS_OS_DIAS},
                {"horario_saida": hora(18, 0), "sentido": "CIRCULAR", "dias": TODOS_OS_DIAS},
            ],
        },
    )
    return rota


def _apelidos_da_viagem(rota, sentido):
    horario = HorarioRota.query.filter_by(rota_id=rota.id, sentido=sentido).first()
    viagem = Viagem.query.filter_by(horario_rota_id=horario.id).first()
    pontos = ViagemPonto.query.filter_by(viagem_id=viagem.id).order_by(ViagemPonto.ordem).all()
    return [vp.ponto.apelido for vp in pontos]


def test_viagem_so_recebe_os_pontos_do_seu_sentido(_db, gestor, prefeitura):
    rota = _rota_com_ponto_de_ida_e_de_volta(gestor, prefeitura)

    assert _apelidos_da_viagem(rota, "IDA") == ["Bairro", "Escola"]
    assert _apelidos_da_viagem(rota, "VOLTA") == ["Escola", "Bairro (volta)"]
    assert _apelidos_da_viagem(rota, "CIRCULAR") == ["Bairro", "Escola", "Bairro (volta)"]


def test_lista_de_pontos_da_rota_filtra_por_sentido(_db, gestor, prefeitura):
    rota = _rota_com_ponto_de_ida_e_de_volta(gestor, prefeitura)
    usuario = str(gestor.user.id)

    todos = rotas_service.get_pontos_by_rota(usuario, str(rota.id))
    ida = rotas_service.get_pontos_by_rota(usuario, str(rota.id), "IDA")
    volta = rotas_service.get_pontos_by_rota(usuario, str(rota.id), "VOLTA")

    assert [p["apelido"] for p in todos] == ["Bairro", "Escola", "Bairro (volta)"]
    assert [p["sentido"] for p in todos] == ["IDA", "AMBOS", "VOLTA"]
    assert [p["apelido"] for p in ida] == ["Bairro", "Escola"]
    assert [p["apelido"] for p in volta] == ["Escola", "Bairro (volta)"]


def test_endpoint_aceita_sentido_na_consulta(_db, gestor, prefeitura):
    rota = _rota_com_ponto_de_ida_e_de_volta(gestor, prefeitura)

    resposta = gestor.client.get(f"/v1/rotas/{rota.id}/pontos?sentido=ida")

    assert resposta.status_code == 200
    assert [p["apelido"] for p in resposta.get_json()["items"]] == ["Bairro", "Escola"]


def test_ponto_sem_sentido_informado_vale_nos_dois(_db, gestor, prefeitura):
    ponto = PontoFactory(prefeitura_id=prefeitura.id, apelido="Sem sentido")
    db.session.add(ponto)
    db.session.commit()
    rota = rotas_service.create_rota(
        str(gestor.user.id),
        {"nome": "Rota simples", "pontos": [{"ponto_id": str(ponto.id), "ordem": 1}]},
    )

    ida = rotas_service.get_pontos_by_rota(str(gestor.user.id), str(rota.id), "IDA")
    volta = rotas_service.get_pontos_by_rota(str(gestor.user.id), str(rota.id), "VOLTA")

    assert [p["apelido"] for p in ida] == ["Sem sentido"]
    assert [p["apelido"] for p in volta] == ["Sem sentido"]
