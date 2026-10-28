"""Escolha dos pontos ao confirmar presença: IDA, VOLTA, CIRCULAR, lembrar e agenda."""

from datetime import date, time, timedelta

import pytest

from app.models.enum import SentidoViagem, StatusViagem
from app.models.geo import Ponto
from app.models.rota import HorarioRota, RotaAluno, RotaPonto
from app.models.viagem import Viagem

pytestmark = pytest.mark.integration


@pytest.fixture()
def ponto_b(_db, prefeitura, rota):
    p = Ponto(prefeitura_id=prefeitura.id, latitude=-7.4, longitude=-35.6, apelido="Ponto B")
    _db.session.add(p)
    _db.session.flush()
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=p.id, ordem=2))
    _db.session.commit()
    return p


@pytest.fixture()
def ponto_fora(_db, prefeitura):
    p = Ponto(prefeitura_id=prefeitura.id, latitude=-7.5, longitude=-35.5, apelido="Fora")
    _db.session.add(p)
    _db.session.commit()
    return p


def _viagem(_db, rota, motorista, sentido, dias=3):
    horario = HorarioRota(rota_id=rota.id, horario_saida=time(7, 0), sentido=sentido)
    _db.session.add(horario)
    _db.session.flush()
    viagem = Viagem(
        data=date.today() + timedelta(days=dias),
        horario_rota_id=horario.id,
        status=StatusViagem.AGENDADA,
        motorista_id=motorista.user.id,
    )
    _db.session.add(viagem)
    _db.session.commit()
    return viagem


def _confirmar(aluno, viagem, **corpo):
    corpo.setdefault("confirmacao", True)
    return aluno.client.put(f"/v1/viagens/{viagem.id}/confirmacao", json=corpo)


def _inscricao(_db, rota, aluno):
    _db.session.expire_all()
    return _db.session.get(RotaAluno, (rota.id, aluno.user.id))


@pytest.fixture()
def cenario(aluno_com_instituicao, rota, rota_aluno, rota_ponto, ponto_b, motorista, _db):
    return aluno_com_instituicao


# ─── IDA ────────────────────────────────────────────────────────────────────


def test_ida_embarque_do_corpo_e_destino_na_instituicao(
    _db, cenario, rota, motorista, ponto, ponto_instituicao
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    r = _confirmar(cenario, viagem, ponto_embarque_id=str(ponto.id))
    assert r.status_code == 200, r.get_data(as_text=True)
    registro = _db.session.get(type(viagem.alunos_confirmados[0]), (viagem.id, cenario.user.id))
    assert registro.ponto_embarque_id == ponto.id
    assert registro.ponto_destino_id == ponto_instituicao.id


def test_ida_sem_lembrar_nao_grava_nem_apaga_padrao(_db, cenario, rota, motorista, ponto, ponto_b):
    cenario.client.put(
        f"/v1/rotas/{rota.id}/meu-ponto-embarque", json={"ponto_embarque_id": str(ponto.id)}
    )
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    assert _confirmar(cenario, viagem, ponto_embarque_id=str(ponto_b.id)).status_code == 200
    assert _inscricao(_db, rota, cenario).ponto_embarque_padrao_id == ponto.id


def test_ida_com_lembrar_grava_embarque_padrao_e_depois_nao_pergunta(
    _db, cenario, rota, motorista, ponto_b
):
    primeira = _viagem(_db, rota, motorista, SentidoViagem.IDA, dias=3)
    segunda = _viagem(_db, rota, motorista, SentidoViagem.IDA, dias=4)
    r = _confirmar(cenario, primeira, ponto_embarque_id=str(ponto_b.id), lembrar_escolha=True)
    assert r.status_code == 200
    assert _inscricao(_db, rota, cenario).ponto_embarque_padrao_id == ponto_b.id
    assert _inscricao(_db, rota, cenario).ponto_desembarque_padrao_id is None
    r2 = _confirmar(cenario, segunda)
    assert r2.status_code == 200
    assert r2.get_json()["ponto_embarque"] == ponto_b.apelido


def test_ida_sem_ponto_e_sem_padrao_da_400_com_campo(_db, cenario, rota, motorista):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    r = _confirmar(cenario, viagem)
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == "ponto_embarque_id"


def test_ida_ponto_de_outra_rota_da_400_com_campo(_db, cenario, rota, motorista, ponto_fora):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    r = _confirmar(cenario, viagem, ponto_embarque_id=str(ponto_fora.id), lembrar_escolha=True)
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == "ponto_embarque_id"
    assert _inscricao(_db, rota, cenario).ponto_embarque_padrao_id is None


def test_ida_aluno_sem_instituicao_da_400_clara(
    _db, aluno, rota, rota_aluno, rota_ponto, ponto, motorista
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    r = _confirmar(aluno, viagem, ponto_embarque_id=str(ponto.id))
    assert r.status_code == 400
    assert "instituição" in r.get_json()["error"]["message"]


# ─── VOLTA ──────────────────────────────────────────────────────────────────


def test_volta_embarca_na_instituicao_e_desce_no_ponto_escolhido(
    _db, cenario, rota, motorista, ponto_b, ponto_instituicao
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.VOLTA)
    r = _confirmar(cenario, viagem, ponto_desembarque_id=str(ponto_b.id))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ponto_embarque"] == "Escola"
    assert r.get_json()["ponto_destino"] == ponto_b.apelido
    assert _inscricao(_db, rota, cenario).ponto_desembarque_padrao_id is None


def test_volta_com_lembrar_grava_desembarque_padrao(_db, cenario, rota, motorista, ponto_b):
    primeira = _viagem(_db, rota, motorista, SentidoViagem.VOLTA, dias=3)
    segunda = _viagem(_db, rota, motorista, SentidoViagem.VOLTA, dias=4)
    _confirmar(cenario, primeira, ponto_desembarque_id=str(ponto_b.id), lembrar_escolha=True)
    inscricao = _inscricao(_db, rota, cenario)
    assert inscricao.ponto_desembarque_padrao_id == ponto_b.id
    assert inscricao.ponto_embarque_padrao_id is None
    assert _confirmar(cenario, segunda).get_json()["ponto_destino"] == ponto_b.apelido


def test_volta_ignora_ponto_de_casa_e_exige_desembarque(_db, cenario, rota, motorista):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.VOLTA)
    r = _confirmar(cenario, viagem)
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == "ponto_desembarque_id"


def test_volta_ponto_de_outra_rota_da_400(_db, cenario, rota, motorista, ponto_fora):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.VOLTA)
    r = _confirmar(cenario, viagem, ponto_desembarque_id=str(ponto_fora.id))
    assert r.status_code == 400
    assert r.get_json()["error"]["details"]["field"] == "ponto_desembarque_id"


def test_volta_aluno_sem_instituicao_da_400(
    _db, aluno, rota, rota_aluno, rota_ponto, ponto, motorista
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.VOLTA)
    r = _confirmar(aluno, viagem, ponto_desembarque_id=str(ponto.id))
    assert r.status_code == 400
    assert "instituição" in r.get_json()["error"]["message"]


# ─── CIRCULAR ───────────────────────────────────────────────────────────────


def test_circular_exige_embarque_e_desembarque_na_rota(
    _db, cenario, rota, motorista, ponto, ponto_b
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.CIRCULAR)
    so_embarque = _confirmar(cenario, viagem, ponto_embarque_id=str(ponto.id))
    assert so_embarque.status_code == 400
    assert so_embarque.get_json()["error"]["details"]["field"] == "ponto_desembarque_id"

    r = _confirmar(
        cenario,
        viagem,
        ponto_embarque_id=str(ponto.id),
        ponto_desembarque_id=str(ponto_b.id),
        lembrar_escolha=True,
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ponto_embarque"] == ponto.apelido
    assert r.get_json()["ponto_destino"] == ponto_b.apelido
    inscricao = _inscricao(_db, rota, cenario)
    assert inscricao.ponto_embarque_padrao_id == ponto.id
    assert inscricao.ponto_desembarque_padrao_id == ponto_b.id


def test_circular_usa_os_padroes_quando_o_corpo_nao_traz(
    _db, cenario, rota, motorista, ponto, ponto_b
):
    cenario.client.put(
        f"/v1/rotas/{rota.id}/meu-ponto-embarque",
        json={"ponto_embarque_id": str(ponto.id), "ponto_desembarque_id": str(ponto_b.id)},
    )
    viagem = _viagem(_db, rota, motorista, SentidoViagem.CIRCULAR)
    assert _confirmar(cenario, viagem).status_code == 200


# ─── cancelar ───────────────────────────────────────────────────────────────


def test_cancelar_nao_apaga_padroes(_db, cenario, rota, motorista, ponto):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    _confirmar(cenario, viagem, ponto_embarque_id=str(ponto.id), lembrar_escolha=True)
    r = _confirmar(cenario, viagem, confirmacao=False)
    assert r.status_code == 200
    assert _inscricao(_db, rota, cenario).ponto_embarque_padrao_id == ponto.id


# ─── agenda ─────────────────────────────────────────────────────────────────


def _item(aluno, viagem):
    itens = aluno.client.get("/v1/viagens/aluno/agenda").get_json()["items"]
    for item in itens:
        if item["viagem_id"] == str(viagem.id):
            return item
    raise AssertionError("viagem fora da agenda")


def test_agenda_ida_pede_escolha_ate_haver_padrao(
    _db, cenario, rota, motorista, ponto, ponto_instituicao
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    item = _item(cenario, viagem)
    assert item["precisa_escolher_ponto"] is True
    assert item["ponto_embarque_id"] is None
    assert item["ponto_destino_id"] == str(ponto_instituicao.id)

    cenario.client.put(
        f"/v1/rotas/{rota.id}/meu-ponto-embarque", json={"ponto_embarque_id": str(ponto.id)}
    )
    item = _item(cenario, viagem)
    assert item["precisa_escolher_ponto"] is False
    assert item["ponto_embarque_id"] == str(ponto.id)


def test_agenda_volta_olha_o_desembarque_padrao(
    _db, cenario, rota, motorista, ponto, ponto_b, ponto_instituicao
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.VOLTA)
    cenario.client.put(
        f"/v1/rotas/{rota.id}/meu-ponto-embarque", json={"ponto_embarque_id": str(ponto.id)}
    )
    item = _item(cenario, viagem)
    assert item["precisa_escolher_ponto"] is True
    assert item["ponto_embarque_id"] == str(ponto_instituicao.id)
    assert item["ponto_destino_id"] is None

    cenario.client.put(
        f"/v1/rotas/{rota.id}/meu-ponto-embarque", json={"ponto_desembarque_id": str(ponto_b.id)}
    )
    item = _item(cenario, viagem)
    assert item["precisa_escolher_ponto"] is False
    assert item["ponto_destino_id"] == str(ponto_b.id)


def test_agenda_confirmada_traz_os_pontos_do_registro(
    _db, cenario, rota, motorista, ponto, ponto_instituicao
):
    viagem = _viagem(_db, rota, motorista, SentidoViagem.IDA)
    _confirmar(cenario, viagem, ponto_embarque_id=str(ponto.id))
    item = _item(cenario, viagem)
    assert item["status_confirmacao"] is True
    assert item["precisa_escolher_ponto"] is False
    assert item["ponto_embarque_id"] == str(ponto.id)
    assert item["ponto_destino_id"] == str(ponto_instituicao.id)
