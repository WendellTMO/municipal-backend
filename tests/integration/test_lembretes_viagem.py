"""Lembretes da viagem: 10 horas antes (alunos da rota) e 10 minutos antes (motorista e confirmados)."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from app.models.enum import StatusViagem
from app.models.notificacao import Notificacao
from app.models.rota import RotaAluno
from app.models.viagem import AlunosConfirmados, Viagem
from app.tasks.notificacao_tasks import verificar_viagens_10min, verificar_viagens_24h


def _viagem_amanha_as_6h(_db, horario_rota, motorista):
    horario_rota.horario_saida = time(6, 0)
    amanha = date.today() + timedelta(days=1)
    viagem = Viagem(
        data=amanha,
        horario_rota_id=horario_rota.id,
        motorista_id=motorista.user.id,
        status=StatusViagem.AGENDADA,
    )
    _db.session.add(viagem)
    _db.session.commit()
    return viagem, datetime.combine(amanha, time(6, 0))


def _rodar(app, tarefa, agora):
    with app.app_context(), patch("app.tasks.notificacao_tasks.scheduler") as agendador:
        agendador.app = app
        tarefa(agora=agora)


def test_lembrete_10h_avisa_os_alunos_da_rota_dentro_da_janela(
    app, _db, aluno, rota, rota_aluno, horario_rota, motorista
):
    viagem, saida = _viagem_amanha_as_6h(_db, horario_rota, motorista)

    _rodar(app, verificar_viagens_24h, saida - timedelta(hours=9, minutes=30))

    aviso = Notificacao.query.filter_by(usuario_id=aluno.user.id).one()
    assert "06:00" in aviso.mensagem
    assert _db.session.get(Viagem, viagem.id).aviso_24h_enviado is True


def test_lembrete_10h_nao_avisa_antes_da_janela_nem_depois_da_saida(
    app, _db, aluno, rota, rota_aluno, horario_rota, motorista
):
    viagem, saida = _viagem_amanha_as_6h(_db, horario_rota, motorista)

    _rodar(app, verificar_viagens_24h, saida - timedelta(hours=11))
    _rodar(app, verificar_viagens_24h, saida + timedelta(minutes=5))

    assert Notificacao.query.filter_by(usuario_id=aluno.user.id).count() == 0
    assert _db.session.get(Viagem, viagem.id).aviso_24h_enviado is False


def test_aviso_de_10_minutos_vai_ao_motorista_e_aos_confirmados(
    app, _db, aluno, other_aluno, rota, rota_aluno, horario_rota, motorista
):
    viagem, saida = _viagem_amanha_as_6h(_db, horario_rota, motorista)
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=other_aluno.user.id))
    _db.session.add(
        AlunosConfirmados(viagem_id=viagem.id, aluno_id=aluno.user.id, confirmacao=True)
    )
    _db.session.add(
        AlunosConfirmados(viagem_id=viagem.id, aluno_id=other_aluno.user.id, confirmacao=False)
    )
    _db.session.commit()

    _rodar(app, verificar_viagens_10min, saida - timedelta(minutes=5))

    assert Notificacao.query.filter_by(usuario_id=motorista.user.id).count() == 1
    assert "06:00" in Notificacao.query.filter_by(usuario_id=aluno.user.id).one().mensagem
    assert Notificacao.query.filter_by(usuario_id=other_aluno.user.id).count() == 0
    assert _db.session.get(Viagem, viagem.id).aviso_10min_enviado is True


def test_aviso_de_10_minutos_espera_a_hora_certa(
    app, _db, aluno, rota, rota_aluno, horario_rota, motorista
):
    viagem, saida = _viagem_amanha_as_6h(_db, horario_rota, motorista)
    _db.session.add(
        AlunosConfirmados(viagem_id=viagem.id, aluno_id=aluno.user.id, confirmacao=True)
    )
    _db.session.commit()

    _rodar(app, verificar_viagens_10min, saida - timedelta(hours=3))

    assert Notificacao.query.count() == 0
    assert _db.session.get(Viagem, viagem.id).aviso_10min_enviado is False
