"""scripts/atualizar_agenda_demo.py: agenda de hoje a hoje+6, idempotente."""

from datetime import date, datetime, time

import pytest

from app.models.enum import StatusViagem
from app.models.viagem import AlunosConfirmados, Viagem
from scripts import atualizar_agenda_demo

pytestmark = pytest.mark.integration


@pytest.fixture()
def demo(_db, rota, motorista, horario_rota, aluno_com_instituicao, rota_aluno, rota_ponto):
    rota.nome = "Galante teste"
    motorista.user.email = "carlos@buska.app"
    horario_rota.horario_saida = time(5, 30)
    _db.session.commit()


def _rodar():
    return atualizar_agenda_demo.atualizar_agenda(date.today(), datetime.now().astimezone())


def test_cria_sete_dias_confirma_aluno_e_e_idempotente(_db, demo, aluno):
    primeira = _rodar()
    assert primeira["viagens_antes"] == 0
    assert primeira["viagens_criadas"] == 7
    assert primeira["viagem_em_andamento"] is not None
    assert primeira["confirmacoes"] == 7

    em_andamento = Viagem.query.filter_by(status=StatusViagem.EM_ANDAMENTO).all()
    assert len(em_andamento) == 1
    assert em_andamento[0].data == date.today()
    assert em_andamento[0].inicio_real is not None
    assert Viagem.query.filter_by(status=StatusViagem.AGENDADA).count() == 6

    segunda = _rodar()
    assert segunda["viagens_antes"] == 7
    assert segunda["viagens_criadas"] == 0
    assert Viagem.query.count() == 7
    confirmados = AlunosConfirmados.query.filter_by(aluno_id=aluno.user.id, confirmacao=True)
    assert confirmados.count() == 7


def test_recusa_banco_remoto_sem_flag(monkeypatch, capsys):
    monkeypatch.setenv("DB_HOST", "db.exemplo.test")
    assert atualizar_agenda_demo.main([]) == 2
    assert "Recusado" in capsys.readouterr().err
