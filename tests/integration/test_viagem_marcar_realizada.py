from datetime import date, timedelta

from app.models.enum import StatusViagem
from app.models.viagem import AlunosConfirmados
from app.services.dashboard_service import relatorio_periodo_gestor
from tests.factories.viagem_factory import ViagemFactory


def _viagem(_db, horario_rota, motorista, dias, status=StatusViagem.AGENDADA):
    v = ViagemFactory(
        horario_rota_id=horario_rota.id,
        data=date.today() + timedelta(days=dias),
        status=status,
        motorista_id=motorista.user.id,
    )
    _db.session.add(v)
    _db.session.commit()
    return v


def _marcar(ator, viagem):
    return ator.client.put(f"/v1/viagens/{viagem.id}/acao", json={"acao": "MARCAR_REALIZADA"})


def test_viagem_que_ja_passou_vira_realizada_sem_app(_db, motorista, horario_rota):
    passada = _viagem(_db, horario_rota, motorista, dias=-1)

    r = _marcar(motorista, passada)

    assert r.status_code == 200
    assert r.get_json()["status"] == "FINALIZADA"
    assert r.get_json()["realizada_sem_app"] is True


def test_viagem_futura_nao_pode_ser_marcada(_db, motorista, horario_rota):
    futura = _viagem(_db, horario_rota, motorista, dias=3)

    r = _marcar(motorista, futura)

    assert r.status_code == 400
    _db.session.refresh(futura)
    assert futura.status == StatusViagem.AGENDADA


def test_so_viagem_agendada_pode_ser_marcada(_db, motorista, horario_rota):
    em_andamento = _viagem(_db, horario_rota, motorista, dias=-1, status=StatusViagem.EM_ANDAMENTO)

    assert _marcar(motorista, em_andamento).status_code == 400


def test_motorista_de_outra_prefeitura_nao_marca(_db, motorista, other_motorista, horario_rota):
    passada = _viagem(_db, horario_rota, motorista, dias=-1)

    assert _marcar(other_motorista, passada).status_code == 404


def test_relatorio_conta_a_viagem_mas_nao_as_vagas_dela(
    _db, gestor, motorista, aluno, horario_rota
):
    passada = _viagem(_db, horario_rota, motorista, dias=-1)
    _db.session.add(
        AlunosConfirmados(viagem_id=passada.id, aluno_id=aluno.user.id, confirmacao=True)
    )
    _db.session.commit()
    _marcar(motorista, passada)

    relatorio = relatorio_periodo_gestor(str(gestor.user.id), str(passada.data), str(passada.data))

    assert relatorio["viagens_realizadas"] == 1
    assert relatorio["vagas_desperdicadas"] == 0
    assert relatorio["alunos_transportados"] == 0
