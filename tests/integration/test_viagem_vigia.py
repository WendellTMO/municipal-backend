"""Viagem em andamento: aviso ao motorista sem movimento há 15 minutos e teto de 5 horas."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from app.models.enum import StatusViagem
from app.models.notificacao import Notificacao
from app.models.viagem import TelemetriaViagem, Viagem
from app.tasks.andamento_tasks import vigiar_viagens_em_andamento

AGORA = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def _viagem_em_andamento(_db, horario_rota, motorista, iniciada_ha):
    viagem = Viagem(
        data=date.today(),
        horario_rota_id=horario_rota.id,
        motorista_id=motorista.user.id,
        status=StatusViagem.EM_ANDAMENTO,
        inicio_real=AGORA - iniciada_ha,
    )
    _db.session.add(viagem)
    _db.session.commit()
    return viagem


def _rastro(_db, viagem, minutos_atras, lat=-7.2300, lon=-35.8800):
    _db.session.add(
        TelemetriaViagem(
            viagem_id=viagem.id,
            latitude=lat,
            longitude=lon,
            timestamp=AGORA - timedelta(minutes=minutos_atras),
        )
    )
    _db.session.commit()


def _rodar(app, _db):
    with app.app_context(), patch("app.tasks.andamento_tasks.scheduler") as agendador:
        agendador.app = app
        resultado = vigiar_viagens_em_andamento(agora=AGORA)
    # A tarefa usa a própria sessão: solta o cache da sessão do teste para reler do banco.
    _db.session.expire_all()
    return resultado


def _avisos(_db, motorista):
    return Notificacao.query.filter_by(usuario_id=motorista.user.id).count()


def test_avisa_uma_vez_o_motorista_parado_ha_15_minutos(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=1))
    for minutos in (14, 10, 5, 1):
        _rastro(_db, viagem, minutos)

    assert _rodar(app, _db) == {"encerradas": 0, "avisadas": 1}
    assert _avisos(_db, motorista) == 1
    assert _db.session.get(Viagem, viagem.id).status == StatusViagem.EM_ANDAMENTO

    assert _rodar(app, _db) == {"encerradas": 0, "avisadas": 0}
    assert _avisos(_db, motorista) == 1


def test_nao_avisa_quando_o_onibus_anda(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=1))
    _rastro(_db, viagem, 14, lat=-7.2300)
    _rastro(_db, viagem, 7, lat=-7.2320)
    _rastro(_db, viagem, 1, lat=-7.2340)

    assert _rodar(app, _db) == {"encerradas": 0, "avisadas": 0}
    assert _avisos(_db, motorista) == 0


def test_avisa_quando_o_app_parou_de_mandar_sinal(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=1))
    _rastro(_db, viagem, 40)

    assert _rodar(app, _db)["avisadas"] == 1


def test_nao_avisa_viagem_que_acabou_de_comecar(app, _db, horario_rota, motorista):
    _viagem_em_andamento(_db, horario_rota, motorista, timedelta(minutes=10))

    assert _rodar(app, _db) == {"encerradas": 0, "avisadas": 0}


def test_avisa_de_novo_se_o_onibus_andou_e_parou_outra_vez(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=1))
    _rastro(_db, viagem, 10)
    _rastro(_db, viagem, 1)
    _rodar(app, _db)
    assert _db.session.get(Viagem, viagem.id).aviso_parada_enviado is True

    _rastro(_db, viagem, 0, lat=-7.2500)
    _rodar(app, _db)
    assert _db.session.get(Viagem, viagem.id).aviso_parada_enviado is False


def test_encerra_com_5_horas_e_calcula_os_km(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=5))
    _rastro(_db, viagem, 200, lat=-7.2300)
    _rastro(_db, viagem, 100, lat=-7.2400)

    assert _rodar(app, _db) == {"encerradas": 1, "avisadas": 0}
    encerrada = _db.session.get(Viagem, viagem.id)
    assert encerrada.status == StatusViagem.FINALIZADA
    assert encerrada.fim_real == viagem.inicio_real + timedelta(hours=5)
    assert float(encerrada.km_real) > 1
    assert _avisos(_db, motorista) == 1


def test_nao_encerra_antes_de_5_horas(app, _db, horario_rota, motorista):
    viagem = _viagem_em_andamento(_db, horario_rota, motorista, timedelta(hours=4, minutes=59))
    _rastro(_db, viagem, 5, lat=-7.2300)
    _rastro(_db, viagem, 1, lat=-7.2400)

    assert _rodar(app, _db) == {"encerradas": 0, "avisadas": 0}
    assert _db.session.get(Viagem, viagem.id).status == StatusViagem.EM_ANDAMENTO
