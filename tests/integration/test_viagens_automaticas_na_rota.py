from datetime import date, timedelta
from datetime import time as hora

from app.models.base import db
from app.models.enum import StatusViagem
from app.models.rota import HorarioRota
from app.models.viagem import Viagem
from app.services import rotas_service
from tests.factories.user_factory import MotoristaFactory
from tests.integration.test_viagens_service_characterization import _horario_operando_em, _viagem

TODOS_OS_DIAS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]


def _viagens_da_rota(rota):
    return (
        db.session.query(Viagem)
        .join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
        .filter(HorarioRota.rota_id == rota.id)
        .all()
    )


def test_horario_adicionado_depois_ja_gera_os_14_dias(_db, gestor, rota):
    rotas_service.add_horario(
        str(gestor.user.id),
        str(rota.id),
        {"horario_saida": hora(7, 0), "sentido": "IDA", "dias": TODOS_OS_DIAS},
    )

    viagens = _viagens_da_rota(rota)
    datas = sorted(v.data for v in viagens)
    hoje = date.today()
    assert datas == [hoje + timedelta(days=i) for i in range(14)]
    for viagem in viagens:
        assert viagem.motorista_id == rota.motorista_padrao_id
        assert viagem.veiculo_id == rota.veiculo_padrao_id


def test_rota_criada_pelo_motorista_gera_viagens(_db, motorista, onibus):
    rota = rotas_service.create_rota(
        str(motorista.user.id),
        {
            "nome": "Rota do motorista",
            "veiculo_padrao_id": onibus.id,
            "horarios": [{"horario_saida": hora(7, 0), "sentido": "IDA", "dias": TODOS_OS_DIAS}],
        },
    )

    viagens = _viagens_da_rota(rota)
    assert len(viagens) == 14
    assert {v.motorista_id for v in viagens} == {motorista.user.id}


def test_trocar_motorista_atualiza_so_as_viagens_futuras_agendadas(_db, gestor, rota, prefeitura):
    novo = MotoristaFactory(prefeitura_id=prefeitura.id)
    _db.session.add(novo)
    _db.session.commit()
    hoje = date.today()
    horario = _horario_operando_em(_db, rota, hoje + timedelta(days=3))
    futura = _viagem(_db, horario, hoje + timedelta(days=3))
    em_andamento = _viagem(
        _db, horario, hoje + timedelta(days=4), status=StatusViagem.EM_ANDAMENTO
    )
    finalizada = _viagem(_db, horario, hoje + timedelta(days=5), status=StatusViagem.FINALIZADA)
    passada = _viagem(_db, horario, hoje - timedelta(days=2))

    rotas_service.update_rota(str(gestor.user.id), str(rota.id), {"motorista_padrao_id": novo.id})

    for viagem in (futura, em_andamento, finalizada, passada):
        _db.session.refresh(viagem)
    assert futura.motorista_id == novo.id
    assert em_andamento.motorista_id != novo.id
    assert finalizada.motorista_id != novo.id
    assert passada.motorista_id != novo.id


def test_trocar_so_o_nome_nao_mexe_nas_viagens(_db, gestor, rota):
    amanha = date.today() + timedelta(days=1)
    horario = _horario_operando_em(_db, rota, amanha)
    viagem = _viagem(_db, horario, amanha, motorista_id=None)

    rotas_service.update_rota(str(gestor.user.id), str(rota.id), {"nome": "Outro nome"})

    _db.session.refresh(viagem)
    assert viagem.motorista_id is None
