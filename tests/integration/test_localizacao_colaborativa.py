from datetime import UTC, date, datetime, timedelta
from datetime import time as hora

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.geo import Ponto
from app.models.notificacao import Notificacao
from app.models.rota import HorarioRota, RotaAluno, RotaPonto
from app.models.viagem import AlunosConfirmados, Viagem, ViagemPonto, ViagemRelato
from app.services import localizacao_colaborativa_service as colaborativa
from app.tasks.notificacao_tasks import verificar_viagens_10min
from tests.factories.user_factory import AlunoFactory
from tests.integration.test_lembretes_viagem import _rodar

# 0.001 grau de latitude tem cerca de 111 metros.
LON = -35.88
PONTOS = [(-7.230, "A"), (-7.235, "B"), (-7.240, "C"), (-7.245, "D")]


@pytest.fixture()
def ligada(monkeypatch):
    monkeypatch.setenv("LOCALIZACAO_COLABORATIVA", "1")


def _viagem_com_pontos(prefeitura, rota):
    """Viagem de hoje, que sai agora e não tem motorista, com 4 pontos em linha."""
    saida = datetime.now().replace(second=0, microsecond=0).time()
    horario = HorarioRota(rota_id=rota.id, horario_saida=saida, sentido="IDA")
    db.session.add(horario)
    db.session.flush()
    viagem = Viagem(
        data=date.today(), horario_rota_id=horario.id, status=StatusViagem.AGENDADA
    )
    db.session.add(viagem)
    db.session.flush()
    for ordem, (lat, apelido) in enumerate(PONTOS, start=1):
        ponto = Ponto(prefeitura_id=prefeitura.id, latitude=lat, longitude=LON, apelido=apelido)
        db.session.add(ponto)
        db.session.flush()
        db.session.add(RotaPonto(rota_id=rota.id, ponto_id=ponto.id, ordem=ordem))
        db.session.add(ViagemPonto(viagem_id=viagem.id, ponto_id=ponto.id, ordem=ordem))
    db.session.commit()
    return viagem


def _aluno_confirmado(prefeitura, rota, viagem):
    aluno = AlunoFactory(prefeitura_id=prefeitura.id)
    db.session.add(aluno)
    db.session.flush()
    db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.id))
    db.session.add(AlunosConfirmados(viagem_id=viagem.id, aluno_id=aluno.id, confirmacao=True))
    db.session.commit()
    return aluno


def _visitados(viagem):
    paradas = ViagemPonto.query.filter_by(viagem_id=viagem.id).order_by(ViagemPonto.ordem).all()
    return [p.visitado for p in paradas]


def _enviar(aluno, viagem, lat, precisao=10):
    return colaborativa.enviar_relato(
        str(aluno.id), str(viagem.id), {"latitude": lat, "longitude": LON, "precisao": precisao}
    )


def test_desligada_o_recurso_nao_existe(_db, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)

    with pytest.raises(NotFoundError):
        _enviar(aluno, viagem, -7.230)
    assert colaborativa.estado(str(aluno.id), str(viagem.id)) == {"ativa": False}


def test_primeiro_envio_inicia_a_viagem_sem_motorista(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)

    resposta = _enviar(aluno, viagem, -7.230)

    _db.session.refresh(viagem)
    assert resposta["aceito"] is True
    assert viagem.status == StatusViagem.EM_ANDAMENTO
    assert viagem.inicio_real is not None
    assert abs(float(viagem.motorista_lat) - (-7.230)) < 0.0001
    assert _visitados(viagem) == [True, False, False, False]


def test_quem_comeca_no_meio_do_percurso_deixa_os_anteriores_como_feitos(
    _db, ligada, prefeitura, rota
):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)

    _enviar(aluno, viagem, -7.240)

    assert _visitados(viagem) == [True, True, True, False]


def test_chegar_ao_ultimo_ponto_finaliza_e_apaga_as_leituras(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)

    _enviar(aluno, viagem, -7.245)

    _db.session.refresh(viagem)
    assert viagem.status == StatusViagem.FINALIZADA
    assert ViagemRelato.query.filter_by(viagem_id=viagem.id).count() == 0


def test_dois_alunos_juntam_as_leituras_numa_posicao(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    um = _aluno_confirmado(prefeitura, rota, viagem)
    dois = _aluno_confirmado(prefeitura, rota, viagem)

    _enviar(um, viagem, -7.2310, precisao=10)
    _enviar(dois, viagem, -7.2312, precisao=10)

    _db.session.refresh(viagem)
    assert -7.2312 <= float(viagem.motorista_lat) <= -7.2308


def test_aluno_sem_confirmacao_nao_compartilha(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)
    AlunosConfirmados.query.filter_by(viagem_id=viagem.id).delete()
    db.session.commit()

    with pytest.raises(ValidationError):
        _enviar(aluno, viagem, -7.230)


def test_fora_da_janela_de_horario_nao_compartilha(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)
    horario = db.session.get(HorarioRota, viagem.horario_rota_id)
    horario.horario_saida = (datetime.now() - timedelta(hours=4)).time()
    db.session.commit()

    with pytest.raises(ValidationError):
        _enviar(aluno, viagem, -7.230)


def test_leitura_imprecisa_e_recusada_sem_mexer_no_onibus(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)

    resposta = _enviar(aluno, viagem, -7.230, precisao=200)

    _db.session.refresh(viagem)
    assert resposta == {"aceito": False, "motivo": "precisao"}
    assert viagem.status == StatusViagem.AGENDADA
    assert viagem.motorista_lat is None


def test_parar_de_compartilhar_apaga_a_leitura_do_aluno(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)
    _enviar(aluno, viagem, -7.230)

    estado = colaborativa.estado(str(aluno.id), str(viagem.id))
    colaborativa.parar_relato(str(aluno.id), str(viagem.id))

    assert estado["eu_compartilhando"] is True
    assert estado["compartilhando"] == 1
    assert ViagemRelato.query.filter_by(viagem_id=viagem.id).count() == 0


def test_pedido_avisa_os_outros_confirmados_e_so_se_repete_depois_de_15_minutos(
    _db, ligada, prefeitura, rota
):
    viagem = _viagem_com_pontos(prefeitura, rota)
    quem_pede = _aluno_confirmado(prefeitura, rota, viagem)
    outro = _aluno_confirmado(prefeitura, rota, viagem)

    primeiro = colaborativa.pedir_localizacao(str(quem_pede.id), str(viagem.id))
    segundo = colaborativa.pedir_localizacao(str(quem_pede.id), str(viagem.id))

    assert primeiro == {"avisados": 1}
    assert segundo == {"avisados": 0, "motivo": "recente"}
    assert Notificacao.query.filter_by(usuario_id=outro.id).count() == 1
    assert Notificacao.query.filter_by(usuario_id=quem_pede.id).count() == 0

    viagem.pedido_colaborativo_em = datetime.now(UTC) - timedelta(minutes=16)
    db.session.commit()
    assert colaborativa.pedir_localizacao(str(quem_pede.id), str(viagem.id)) == {"avisados": 1}


def test_pedido_respeita_quem_desligou_as_notificacoes(_db, ligada, prefeitura, rota):
    viagem = _viagem_com_pontos(prefeitura, rota)
    quem_pede = _aluno_confirmado(prefeitura, rota, viagem)
    silencioso = _aluno_confirmado(prefeitura, rota, viagem)
    silencioso.receber_notificacoes = False
    db.session.commit()

    resposta = colaborativa.pedir_localizacao(str(quem_pede.id), str(viagem.id))

    assert resposta == {"avisados": 0}
    assert Notificacao.query.filter_by(usuario_id=silencioso.id).count() == 0


def test_estado_traz_o_destino_do_aluno_para_o_app_perguntar_se_chegou(
    _db, ligada, prefeitura, rota
):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)
    destino = ViagemPonto.query.filter_by(viagem_id=viagem.id, ordem=4).one()
    confirmacao = db.session.get(AlunosConfirmados, (viagem.id, aluno.id))
    confirmacao.ponto_destino_id = destino.ponto_id
    db.session.commit()

    estado = colaborativa.estado(str(aluno.id), str(viagem.id))

    assert estado["destino"]["nome"] == "D"
    assert abs(estado["destino"]["latitude"] - (-7.245)) < 0.0001


def test_lembrete_de_10_minutos_chega_aos_alunos_mesmo_sem_motorista(
    app, _db, ligada, prefeitura, rota
):
    viagem = _viagem_com_pontos(prefeitura, rota)
    aluno = _aluno_confirmado(prefeitura, rota, viagem)
    horario = db.session.get(HorarioRota, viagem.horario_rota_id)
    saida = datetime.combine(viagem.data, hora(12, 0))
    horario.horario_saida = hora(12, 0)
    db.session.commit()

    _rodar(app, verificar_viagens_10min, saida - timedelta(minutes=5))

    aviso = Notificacao.query.filter_by(usuario_id=aluno.id).one()
    assert "Compartilhar localização" in aviso.mensagem
    assert db.session.get(Viagem, viagem.id).aviso_10min_enviado is True
