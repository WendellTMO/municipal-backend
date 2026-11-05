"""Viagem agendada que passa 24 horas da saída sem começar vira cancelada (não realizada)."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from app.models.enum import StatusViagem
from app.models.viagem import Viagem
from app.services import viagens_service
from app.tasks.expiracao_tasks import MOTIVO_NAO_REALIZADA, cancelar_viagens_nao_realizadas


def _viagem_ontem_as_6h(_db, horario_rota, motorista, status=StatusViagem.AGENDADA):
    horario_rota.horario_saida = time(6, 0)
    ontem = date.today() - timedelta(days=1)
    viagem = Viagem(
        data=ontem,
        horario_rota_id=horario_rota.id,
        motorista_id=motorista.user.id,
        status=status,
    )
    _db.session.add(viagem)
    _db.session.commit()
    return viagem, datetime.combine(ontem, time(6, 0))


def _rodar(app, _db, agora):
    with app.app_context(), patch("app.tasks.expiracao_tasks.scheduler") as agendador:
        agendador.app = app
        total = cancelar_viagens_nao_realizadas(agora=agora)
    # A tarefa usa a própria sessão: solta o cache da sessão do teste para reler do banco.
    _db.session.expire_all()
    return total


def test_cancela_so_depois_de_24_horas_da_saida(app, _db, horario_rota, motorista):
    viagem, saida = _viagem_ontem_as_6h(_db, horario_rota, motorista)

    assert _rodar(app, _db, saida + timedelta(hours=23, minutes=59)) == 0
    assert _db.session.get(Viagem, viagem.id).status == StatusViagem.AGENDADA

    assert _rodar(app, _db, saida + timedelta(hours=24)) == 1
    cancelada = _db.session.get(Viagem, viagem.id)
    assert cancelada.status == StatusViagem.CANCELADA
    assert cancelada.motivo_cancelamento == MOTIVO_NAO_REALIZADA


def test_nao_mexe_em_viagem_em_andamento(app, _db, horario_rota, motorista):
    viagem, saida = _viagem_ontem_as_6h(_db, horario_rota, motorista, StatusViagem.EM_ANDAMENTO)

    assert _rodar(app, _db, saida + timedelta(days=3)) == 0
    assert _db.session.get(Viagem, viagem.id).status == StatusViagem.EM_ANDAMENTO


def test_motorista_ainda_confirma_que_a_viagem_cancelada_pelo_prazo_foi_feita(
    app, _db, horario_rota, motorista
):
    viagem, saida = _viagem_ontem_as_6h(_db, horario_rota, motorista)
    _rodar(app, _db, saida + timedelta(hours=25))

    with app.app_context():
        viagens_service.controlar_viagem(
            str(motorista.user.id), str(viagem.id), {"acao": "MARCAR_REALIZADA"}
        )

    _db.session.expire_all()
    refeita = _db.session.get(Viagem, viagem.id)
    assert refeita.status == StatusViagem.FINALIZADA
    assert refeita.motivo_cancelamento is None
    assert refeita.realizada_sem_app is True
