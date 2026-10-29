"""Characterization tests for ``app/services/viagens_service.py``.

Purpose: pin the CURRENT observable behaviour of every public function in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests: where the behaviour pinned here is a known
bug, the test name and comment say so. If one of these tests changes in
the SAME PR that changes the behaviour of
`viagens_service.py`, the change was not a refactor.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.enum import DiaDaSemana, SentidoViagem, StatusViagem
from app.models.geo import Ponto
from app.models.notificacao import Notificacao
from app.models.rota import DiasOperacao, HorarioRota, RotaPonto
from app.models.viagem import AlunosConfirmados, TelemetriaViagem, Viagem, ViagemPonto
from app.services import viagens_service
from app.services.viagens_service import (
    atualizar_localizacao,
    atualizar_localizacao_aluno,
    cancelar_viagem,
    confirmar_presenca_aluno,
    controlar_viagem,
    gerar_viagem,
    gerar_viagens_em_lote,
    gerar_viagens_periodo,
    get_proximas_viagens_aluno,
    list_viagens_gestor,
    list_viagens_motorista,
    listar_pontos_embarque,
    obter_localizacao_onibus,
)

pytestmark = pytest.mark.integration


# ─── helpers ────────────────────────────────────────────────────────────────

_DIAS = [
    DiaDaSemana.SEG,
    DiaDaSemana.TER,
    DiaDaSemana.QUA,
    DiaDaSemana.QUI,
    DiaDaSemana.SEX,
    DiaDaSemana.SAB,
    DiaDaSemana.DOM,
]


def _dia_de(data_obj: date) -> DiaDaSemana:
    return _DIAS[data_obj.weekday()]


def _horario_operando_em(_db, rota, data_obj, sentido=SentidoViagem.IDA, hora=time(7, 30)):
    """HorarioRota da rota com um DiasOperacao no dia da semana de ``data_obj``."""
    h = HorarioRota(rota_id=rota.id, horario_saida=hora, sentido=sentido)
    _db.session.add(h)
    _db.session.flush()
    _db.session.add(DiasOperacao(horario_rota_id=h.id, dia=_dia_de(data_obj)))
    _db.session.commit()
    return h


def _viagem(_db, horario, data_obj, status=StatusViagem.AGENDADA, motorista_id=None, **kwargs):
    v = Viagem(
        data=data_obj,
        horario_rota_id=horario.id if horario else None,
        status=status,
        motorista_id=motorista_id,
        **kwargs,
    )
    _db.session.add(v)
    _db.session.commit()
    return v


def _ponto(_db, prefeitura_id, lat, lon, apelido="Ponto"):
    p = Ponto(prefeitura_id=prefeitura_id, latitude=lat, longitude=lon, apelido=apelido)
    _db.session.add(p)
    _db.session.commit()
    return p


def _confirmacao(_db, viagem, aluno_id, **kwargs):
    conf = AlunosConfirmados(viagem_id=viagem.id, aluno_id=aluno_id, **kwargs)
    _db.session.add(conf)
    _db.session.commit()
    return conf


# ─── get_proximas_viagens_aluno ─────────────────────────────────────────────


def test_get_proximas_viagens_aluno_recusa_gestor(_db, gestor):
    with pytest.raises(ForbiddenError) as exc:
        get_proximas_viagens_aluno(str(gestor.user.id))

    assert exc.value.message == "Apenas alunos podem ver sua agenda de viagens"
    assert exc.value.status_code == 403


def test_get_proximas_viagens_aluno_usuario_inexistente_403(_db, prefeitura):
    # Usuário que não existe cai no mesmo 403 do papel errado, sem 404.
    with pytest.raises(ForbiddenError):
        get_proximas_viagens_aluno(str(uuid.uuid4()))


def test_get_proximas_viagens_aluno_retorna_viagem_agendada_da_rota_inscrita(
    _db, aluno, rota, rota_aluno, horario_rota
):
    viagem = _viagem(_db, horario_rota, date.today() + timedelta(days=3))

    resultado = get_proximas_viagens_aluno(str(aluno.user.id))

    assert [v.id for v in resultado] == [viagem.id]


def test_get_proximas_viagens_aluno_ignora_viagem_passada(
    _db, aluno, rota, rota_aluno, horario_rota
):
    _viagem(_db, horario_rota, date.today() - timedelta(days=1))

    assert get_proximas_viagens_aluno(str(aluno.user.id)) == []


def test_get_proximas_viagens_aluno_ignora_status_finalizada_e_cancelada(
    _db, aluno, rota, rota_aluno, horario_rota
):
    _viagem(_db, horario_rota, date.today() + timedelta(days=1), status=StatusViagem.FINALIZADA)
    _viagem(_db, horario_rota, date.today() + timedelta(days=2), status=StatusViagem.CANCELADA)

    assert get_proximas_viagens_aluno(str(aluno.user.id)) == []


def test_get_proximas_viagens_aluno_inclui_em_andamento(_db, aluno, rota, rota_aluno, horario_rota):
    viagem = _viagem(
        _db, horario_rota, date.today() + timedelta(days=1), status=StatusViagem.EM_ANDAMENTO
    )

    assert [v.id for v in get_proximas_viagens_aluno(str(aluno.user.id))] == [viagem.id]


def test_get_proximas_viagens_aluno_corta_pela_data_local(
    _db, aluno, rota, rota_aluno, horario_rota
):
    """Corrigido: o corte usa `date.today()`, a data local.

    O `docker-compose.prod.yml` define `TZ: America/Sao_Paulo`, então "hoje"
    para o aluno é a data brasileira. Antes esta função usava
    `datetime.now(UTC).date()` enquanto o `gerar_viagens_periodo` gerava com
    `date.today()`: entre 21h e meia-noite a data UTC virava antes e a viagem
    de hoje sumia da agenda, justamente quando o aluno mais a consultaria.

    Este teste é determinístico a qualquer hora porque usa a mesma referência
    do serviço. Foi um teste meu flaky que revelou o problema.
    """
    hoje = date.today()

    de_ontem = _viagem(_db, horario_rota, hoje - timedelta(days=1))
    de_hoje = _viagem(_db, horario_rota, hoje)

    ids = [v.id for v in get_proximas_viagens_aluno(str(aluno.user.id))]

    assert de_hoje.id in ids
    assert de_ontem.id not in ids


def test_get_proximas_viagens_aluno_sem_inscricao_devolve_vazio(_db, aluno, horario_rota):
    _viagem(_db, horario_rota, date.today() + timedelta(days=3))

    assert get_proximas_viagens_aluno(str(aluno.user.id)) == []


def test_get_proximas_viagens_aluno_nao_vaza_viagem_de_outro_aluno(
    _db, aluno, other_aluno, rota, rota_aluno, horario_rota
):
    _viagem(_db, horario_rota, date.today() + timedelta(days=3))

    assert get_proximas_viagens_aluno(str(other_aluno.user.id)) == []


# ─── confirmar_presenca_aluno ───────────────────────────────────────────────


def test_confirmar_presenca_recusa_gestor(_db, gestor, viagem_futura_agendada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        confirmar_presenca_aluno(
            str(gestor.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"confirmacao": False},
        )

    assert exc.value.message == "Aluno não encontrado"


def test_confirmar_presenca_viagem_inexistente_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        confirmar_presenca_aluno(str(aluno.user.id), str(uuid.uuid4()), {"confirmacao": False})

    assert exc.value.message == "Viagem não encontrada"


def test_confirmar_presenca_sem_inscricao_na_rota_403(
    _db, aluno, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        confirmar_presenca_aluno(
            str(aluno.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"confirmacao": False},
        )

    assert exc.value.message == "Você não está inscrito na rota desta viagem"


def test_confirmar_presenca_cria_registro_negativo_quando_nao_existe(
    _db, aluno, rota_aluno, viagem_futura_agendada_com_motorista
):
    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": False},
    )

    assert registro.confirmacao is False
    assert registro.ponto_embarque_id is None
    assert (
        _db.session.get(
            AlunosConfirmados,
            (viagem_futura_agendada_com_motorista.id, aluno.user.id),
        )
        is not None
    )


def test_confirmar_presenca_com_ponto_fora_da_rota_400(
    _db, aluno, prefeitura, rota_aluno, viagem_futura_agendada_com_motorista
):
    ponto_alheio = _ponto(_db, prefeitura.id, -23.0, -46.0, "Fora da rota")

    with pytest.raises(ValidationError) as exc:
        confirmar_presenca_aluno(
            str(aluno.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"confirmacao": True, "ponto_embarque_id": str(ponto_alheio.id)},
        )

    assert exc.value.details["field"] == "ponto_embarque_id"


def test_confirmar_presenca_confirma_e_grava_ponto_de_embarque(
    _db,
    aluno,
    aluno_com_instituicao,
    ponto,
    rota_aluno,
    rota_ponto,
    viagem_futura_agendada_com_motorista,
):
    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": True, "ponto_embarque_id": str(ponto.id)},
    )

    assert registro.confirmacao is True
    assert str(registro.ponto_embarque_id) == str(ponto.id)


def test_confirmar_presenca_volta_embarca_na_instituicao_e_desce_no_ponto_escolhido(
    _db, aluno, aluno_com_instituicao, ponto_instituicao, rota, rota_aluno, rota_ponto, ponto
):
    horario = _horario_operando_em(
        _db, rota, date.today() + timedelta(days=5), sentido=SentidoViagem.VOLTA
    )
    viagem = _viagem(_db, horario, date.today() + timedelta(days=5))

    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem.id),
        {"confirmacao": True, "ponto_desembarque_id": str(ponto.id)},
    )

    assert registro.ponto_embarque_id == ponto_instituicao.id
    assert registro.ponto_destino_id == ponto.id


def test_confirmar_presenca_sem_ponto_usa_o_padrao_da_inscricao(
    _db,
    aluno,
    aluno_com_instituicao,
    rota_aluno,
    rota_ponto,
    ponto,
    viagem_futura_agendada_com_motorista,
):
    rota_aluno.ponto_embarque_padrao_id = ponto.id
    _db.session.commit()

    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": True},
    )

    assert registro.confirmacao is True
    assert registro.ponto_embarque_id == ponto.id


def test_confirmar_presenca_sem_ponto_e_sem_padrao_da_400(
    _db, aluno, rota_aluno, rota_ponto, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        confirmar_presenca_aluno(
            str(aluno.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"confirmacao": True},
        )

    assert "ponto" in exc.value.message


def test_confirmar_presenca_ponto_informado_vence_o_padrao(
    _db,
    aluno,
    aluno_com_instituicao,
    prefeitura,
    rota,
    rota_aluno,
    rota_ponto,
    ponto,
    viagem_futura_agendada_com_motorista,
):
    outro = _ponto(_db, prefeitura.id, -23.2, -46.2, "Outro")
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=outro.id, ordem=2))
    rota_aluno.ponto_embarque_padrao_id = ponto.id
    _db.session.commit()

    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": True, "ponto_embarque_id": str(outro.id)},
    )

    assert registro.ponto_embarque_id == outro.id


def test_confirmar_presenca_ida_sem_instituicao_da_400(
    _db, aluno, rota, rota_aluno, rota_ponto, ponto
):
    horario = _horario_operando_em(
        _db, rota, date.today() + timedelta(days=5), sentido=SentidoViagem.IDA
    )
    viagem = _viagem(_db, horario, date.today() + timedelta(days=5))

    with pytest.raises(ValidationError) as exc:
        confirmar_presenca_aluno(
            str(aluno.user.id),
            str(viagem.id),
            {"confirmacao": True, "ponto_embarque_id": str(ponto.id)},
        )

    assert "instituição" in exc.value.message


def test_confirmar_presenca_desconfirma_limpa_pontos(
    _db,
    aluno,
    aluno_com_instituicao,
    ponto,
    rota_aluno,
    rota_ponto,
    viagem_futura_agendada_com_motorista,
):
    confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": True, "ponto_embarque_id": str(ponto.id)},
    )

    registro = confirmar_presenca_aluno(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"confirmacao": False},
    )

    assert registro.confirmacao is False
    assert registro.ponto_embarque_id is None
    assert registro.ponto_destino_id is None


def test_confirmar_presenca_sem_chave_confirmacao_estoura_key_error(
    _db, aluno, rota_aluno, viagem_futura_agendada_com_motorista
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    ``data["confirmacao"]`` é acesso direto: um payload sem a chave levanta
    ``KeyError``, que o handler genérico transforma em 500. Hoje o schema da
    borda garante a chave, então isso só aparece em chamada direta ao serviço.
    """
    with pytest.raises(KeyError):
        confirmar_presenca_aluno(
            str(aluno.user.id), str(viagem_futura_agendada_com_motorista.id), {}
        )


# ─── listar_pontos_embarque ─────────────────────────────────────────────────


def test_listar_pontos_embarque_recusa_gestor(_db, gestor, viagem_futura_agendada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        listar_pontos_embarque(str(gestor.user.id), str(viagem_futura_agendada_com_motorista.id))

    assert exc.value.message == "Acesso restrito a alunos"


def test_listar_pontos_embarque_viagem_inexistente_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        listar_pontos_embarque(str(aluno.user.id), str(uuid.uuid4()))

    assert exc.value.message == "Viagem não encontrada"


def test_listar_pontos_embarque_sem_inscricao_403(_db, aluno, viagem_futura_agendada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        listar_pontos_embarque(str(aluno.user.id), str(viagem_futura_agendada_com_motorista.id))

    assert exc.value.message == "Você não está inscrito na rota desta viagem"


def test_listar_pontos_embarque_retorna_pontos_ordenados(
    _db, aluno, prefeitura, rota, rota_aluno, horario_rota
):
    p1 = _ponto(_db, prefeitura.id, -23.1, -46.1, "Primeiro")
    p2 = _ponto(_db, prefeitura.id, -23.2, -46.2, "Segundo")
    _db.session.add_all(
        [
            RotaPonto(rota_id=rota.id, ponto_id=p2.id, ordem=2),
            RotaPonto(rota_id=rota.id, ponto_id=p1.id, ordem=1),
        ]
    )
    _db.session.commit()
    viagem = _viagem(_db, horario_rota, date.today() + timedelta(days=2))

    resultado = listar_pontos_embarque(str(aluno.user.id), str(viagem.id))

    assert [p["apelido"] for p in resultado] == ["Primeiro", "Segundo"]
    assert resultado[0].keys() == {"ponto_id", "apelido", "latitude", "longitude", "ordem"}
    assert isinstance(resultado[0]["latitude"], float)


# ─── gerar_viagem ───────────────────────────────────────────────────────────


def test_gerar_viagem_recusa_aluno(_db, aluno, rota):
    with pytest.raises(ForbiddenError) as exc:
        gerar_viagem(
            str(aluno.user.id), {"rota_id": str(rota.id), "data": date.today() + timedelta(days=1)}
        )

    assert exc.value.message == "Permissão negada"


def test_gerar_viagem_sem_data_400(_db, gestor, rota):
    with pytest.raises(ValidationError) as exc:
        gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id)})

    assert exc.value.message == "Data é obrigatória"


def test_gerar_viagem_rota_inexistente_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        gerar_viagem(
            str(gestor.user.id),
            {"rota_id": str(uuid.uuid4()), "data": date.today() + timedelta(days=1)},
        )

    assert exc.value.message == "Rota não encontrada"


def test_gerar_viagem_rota_de_outra_prefeitura_403(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        gerar_viagem(
            str(other_gestor.user.id),
            {"rota_id": str(rota.id), "data": date.today() + timedelta(days=1)},
        )

    assert exc.value.message == "Acesso negado"


def test_gerar_viagem_sem_horario_no_dia_404(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    # Horário existe, mas opera em outro dia da semana.
    _horario_operando_em(_db, rota, alvo + timedelta(days=1))

    with pytest.raises(NotFoundError) as exc:
        gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id), "data": alvo})

    assert "Horário não encontrado para a rota" in exc.value.message


def test_gerar_viagem_cria_viagem_agendada_com_veiculo_padrao(_db, gestor, rota, onibus):
    alvo = date.today() + timedelta(days=1)
    horario = _horario_operando_em(_db, rota, alvo)

    nova = gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id), "data": alvo})

    assert nova.status == StatusViagem.AGENDADA
    assert nova.horario_rota_id == horario.id
    assert nova.veiculo_id == onibus.id
    assert nova.data == alvo


def test_gerar_viagem_copia_alunos_inscritos_e_pontos_da_rota(
    _db, gestor, rota, rota_aluno, rota_ponto, aluno, ponto
):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    nova = gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id), "data": alvo})

    confirmados = AlunosConfirmados.query.filter_by(viagem_id=nova.id).all()
    pontos = ViagemPonto.query.filter_by(viagem_id=nova.id).all()
    assert [c.aluno_id for c in confirmados] == [aluno.user.id]
    assert confirmados[0].confirmacao is False
    assert [(p.ponto_id, p.ordem) for p in pontos] == [(ponto.id, 1)]


def test_gerar_viagem_duplicada_409(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)
    gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id), "data": alvo})

    with pytest.raises(ConflictError) as exc:
        gerar_viagem(str(gestor.user.id), {"rota_id": str(rota.id), "data": alvo})

    assert "Viagem já gerada para este dia/horário" in exc.value.message


def test_gerar_viagem_aceita_motorista_como_papel(_db, motorista, rota):
    # Invariante de hoje: gerar viagem manual não é exclusivo de GESTOR.
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    nova = gerar_viagem(str(motorista.user.id), {"rota_id": str(rota.id), "data": alvo})

    assert nova.status == StatusViagem.AGENDADA


def test_gerar_viagem_usa_motorista_do_payload_sem_validar(_db, gestor, rota, other_motorista):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    ``motorista_id`` vem do payload e é gravado sem checagem de papel nem de
    prefeitura: um motorista de outra prefeitura entra na viagem.
    """
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    nova = gerar_viagem(
        str(gestor.user.id),
        {
            "rota_id": str(rota.id),
            "data": alvo,
            "motorista_id": str(other_motorista.user.id),
        },
    )

    assert nova.motorista_id == other_motorista.user.id


# ─── gerar_viagens_em_lote ──────────────────────────────────────────────────


def test_gerar_viagens_em_lote_recusa_motorista(_db, motorista):
    with pytest.raises(ForbiddenError) as exc:
        gerar_viagens_em_lote(str(motorista.user.id), date.today() + timedelta(days=1))

    assert exc.value.message == "Permissão negada. Apenas gestores podem gerar lote."


def test_gerar_viagens_em_lote_cria_uma_viagem_por_horario_do_dia(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo, hora=time(7, 0))
    _horario_operando_em(_db, rota, alvo, hora=time(17, 0))

    relatorio = gerar_viagens_em_lote(str(gestor.user.id), alvo)

    assert relatorio["total_rotas_analisadas"] == 1
    assert relatorio["viagens_criadas"] == 2
    assert len(relatorio["detalhes"]) == 2


def test_gerar_viagens_em_lote_e_idempotente(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)
    gerar_viagens_em_lote(str(gestor.user.id), alvo)

    relatorio = gerar_viagens_em_lote(str(gestor.user.id), alvo)

    assert relatorio["viagens_criadas"] == 0
    assert Viagem.query.filter_by(data=alvo).count() == 1


def test_gerar_viagens_em_lote_ignora_rota_de_outra_prefeitura(_db, other_gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    relatorio = gerar_viagens_em_lote(str(other_gestor.user.id), alvo)

    assert relatorio["total_rotas_analisadas"] == 0
    assert relatorio["viagens_criadas"] == 0


def test_gerar_viagens_em_lote_usa_motorista_padrao_da_rota(_db, gestor, rota, motorista):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    gerar_viagens_em_lote(str(gestor.user.id), alvo)

    assert Viagem.query.filter_by(data=alvo).one().motorista_id == motorista.user.id


# ─── list_viagens_motorista ─────────────────────────────────────────────────


def test_list_viagens_motorista_retorna_viagens_do_motorista(_db, motorista, horario_rota):
    antiga = _viagem(_db, horario_rota, date.today(), motorista_id=motorista.user.id)
    nova = _viagem(
        _db, horario_rota, date.today() + timedelta(days=5), motorista_id=motorista.user.id
    )

    resultado = list_viagens_motorista(str(motorista.user.id))

    assert [v.id for v in resultado] == [nova.id, antiga.id]


def test_list_viagens_motorista_nao_tem_gate_de_papel(_db, aluno, motorista, horario_rota):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    A função não carrega o usuário nem checa papel ou prefeitura: filtra
    apenas por ``motorista_id``. Um ALUNO chamando direto recebe 200 com lista
    vazia em vez de 403, e qualquer id de motorista devolve a agenda dele.
    """
    _viagem(_db, horario_rota, date.today(), motorista_id=motorista.user.id)

    assert list_viagens_motorista(str(aluno.user.id)) == []
    assert len(list_viagens_motorista(str(motorista.user.id))) == 1


# ─── controlar_viagem ───────────────────────────────────────────────────────


def test_controlar_viagem_usuario_inexistente_404(_db, viagem_futura_agendada_com_motorista):
    with pytest.raises(NotFoundError) as exc:
        controlar_viagem(
            str(uuid.uuid4()),
            str(viagem_futura_agendada_com_motorista.id),
            {"acao": "INICIAR"},
        )

    assert exc.value.message == "Usuário não encontrado"


def test_controlar_viagem_viagem_inexistente_404(_db, motorista):
    with pytest.raises(NotFoundError) as exc:
        controlar_viagem(str(motorista.user.id), str(uuid.uuid4()), {"acao": "INICIAR"})

    assert exc.value.message == "Viagem não encontrada"


def test_controlar_viagem_motorista_de_outra_viagem_403(
    _db, other_motorista, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        controlar_viagem(
            str(other_motorista.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"acao": "INICIAR"},
        )

    assert exc.value.message == "Esta viagem não pertence a você"


def test_controlar_viagem_iniciar_muda_status_e_marca_inicio(
    _db, motorista, viagem_futura_agendada_com_motorista
):
    viagem = controlar_viagem(
        str(motorista.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"acao": "INICIAR"},
    )

    assert viagem.status == StatusViagem.EM_ANDAMENTO
    assert viagem.inicio_real is not None


def test_controlar_viagem_iniciar_notifica_apenas_confirmados(
    _db, motorista, aluno, other_aluno, viagem_futura_agendada_com_motorista
):
    _confirmacao(_db, viagem_futura_agendada_com_motorista, aluno.user.id, confirmacao=True)
    _confirmacao(_db, viagem_futura_agendada_com_motorista, other_aluno.user.id, confirmacao=False)

    controlar_viagem(
        str(motorista.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"acao": "INICIAR"},
    )

    assert Notificacao.query.filter_by(usuario_id=aluno.user.id).count() == 1
    assert Notificacao.query.filter_by(usuario_id=other_aluno.user.id).count() == 0


def test_controlar_viagem_iniciar_com_status_errado_400(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        controlar_viagem(
            str(motorista.user.id),
            str(viagem_futura_iniciada_com_motorista.id),
            {"acao": "INICIAR"},
        )

    assert exc.value.message == "Não é possível iniciar viagem com status EM_ANDAMENTO"


def test_controlar_viagem_finalizar_exige_em_andamento(
    _db, motorista, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        controlar_viagem(
            str(motorista.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"acao": "FINALIZAR"},
        )

    assert exc.value.message == "A viagem precisa estar em andamento para ser finalizada"


def test_controlar_viagem_acao_invalida_400(_db, motorista, viagem_futura_agendada_com_motorista):
    with pytest.raises(ValidationError) as exc:
        controlar_viagem(
            str(motorista.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"acao": "PAUSAR"},
        )

    assert exc.value.message == "Ação inválida. Use INICIAR ou FINALIZAR"


def test_controlar_viagem_gestor_de_outra_prefeitura_inicia_viagem_alheia(
    _db, other_gestor, viagem_futura_agendada_com_motorista
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O único gate é ``role == MOTORISTA and viagem.motorista_id != user.id``.
    Não existe checagem de prefeitura, então um GESTOR de outra prefeitura
    inicia e finaliza viagens que não são dele.
    """
    viagem = controlar_viagem(
        str(other_gestor.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"acao": "INICIAR"},
    )

    assert viagem.status == StatusViagem.EM_ANDAMENTO


def test_controlar_viagem_aluno_tambem_passa_no_gate(
    _db, aluno, viagem_futura_agendada_com_motorista
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O gate só olha para MOTORISTA, então ALUNO passa direto e consegue
    iniciar a viagem.
    """
    viagem = controlar_viagem(
        str(aluno.user.id),
        str(viagem_futura_agendada_com_motorista.id),
        {"acao": "INICIAR"},
    )

    assert viagem.status == StatusViagem.EM_ANDAMENTO


# ─── list_viagens_gestor ────────────────────────────────────────────────────


def test_list_viagens_gestor_recusa_motorista(_db, motorista):
    with pytest.raises(ForbiddenError) as exc:
        list_viagens_gestor(str(motorista.user.id), {})

    assert exc.value.message == "Apenas gestores podem acessar o histórico completo"


def test_list_viagens_gestor_sem_filtros_retorna_viagens_da_prefeitura(_db, gestor, horario_rota):
    viagem = _viagem(_db, horario_rota, date.today())

    assert [v.id for v in list_viagens_gestor(str(gestor.user.id), {})] == [viagem.id]


def test_list_viagens_gestor_nao_vaza_outra_prefeitura(_db, other_gestor, horario_rota):
    _viagem(_db, horario_rota, date.today())

    assert list_viagens_gestor(str(other_gestor.user.id), {}) == []


def test_list_viagens_gestor_filtra_por_status(_db, gestor, horario_rota):
    agendada = _viagem(_db, horario_rota, date.today())
    _viagem(_db, horario_rota, date.today() + timedelta(days=1), status=StatusViagem.CANCELADA)

    resultado = list_viagens_gestor(str(gestor.user.id), {"status": StatusViagem.AGENDADA})

    assert [v.id for v in resultado] == [agendada.id]


def test_list_viagens_gestor_filtra_por_intervalo_de_datas(_db, gestor, horario_rota):
    dentro = _viagem(_db, horario_rota, date.today() + timedelta(days=2))
    _viagem(_db, horario_rota, date.today() + timedelta(days=20))

    resultado = list_viagens_gestor(
        str(gestor.user.id),
        {
            "data_inicio": date.today() + timedelta(days=1),
            "data_fim": date.today() + timedelta(days=3),
        },
    )

    assert [v.id for v in resultado] == [dentro.id]


def test_list_viagens_gestor_filtra_por_motorista_e_rota(
    _db, gestor, rota, motorista, horario_rota
):
    com_motorista = _viagem(_db, horario_rota, date.today(), motorista_id=motorista.user.id)
    _viagem(_db, horario_rota, date.today() + timedelta(days=1))

    por_motorista = list_viagens_gestor(
        str(gestor.user.id), {"motorista_id": str(motorista.user.id)}
    )
    por_rota = list_viagens_gestor(str(gestor.user.id), {"rota_id": str(rota.id)})

    assert [v.id for v in por_motorista] == [com_motorista.id]
    assert len(por_rota) == 2


# ─── cancelar_viagem ────────────────────────────────────────────────────────


def test_cancelar_viagem_recusa_motorista(_db, motorista, viagem_futura_agendada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        cancelar_viagem(str(motorista.user.id), str(viagem_futura_agendada_com_motorista.id))

    assert exc.value.message == "Apenas gestores podem cancelar viagens"


def test_cancelar_viagem_inexistente_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        cancelar_viagem(str(gestor.user.id), str(uuid.uuid4()))

    assert exc.value.message == "Viagem não encontrada"


def test_cancelar_viagem_ja_cancelada_400(_db, gestor, horario_rota):
    viagem = _viagem(_db, horario_rota, date.today(), status=StatusViagem.CANCELADA)

    with pytest.raises(ValidationError) as exc:
        cancelar_viagem(str(gestor.user.id), str(viagem.id))

    assert exc.value.message == "Não é possível cancelar uma viagem com status CANCELADA"


def test_cancelar_viagem_finalizada_400(_db, gestor, horario_rota):
    viagem = _viagem(_db, horario_rota, date.today(), status=StatusViagem.FINALIZADA)

    with pytest.raises(ValidationError):
        cancelar_viagem(str(gestor.user.id), str(viagem.id))


def test_cancelar_viagem_notifica_confirmados_e_muda_status(
    _db, gestor, aluno, other_aluno, viagem_futura_agendada_com_motorista
):
    _confirmacao(_db, viagem_futura_agendada_com_motorista, aluno.user.id, confirmacao=True)
    _confirmacao(_db, viagem_futura_agendada_com_motorista, other_aluno.user.id, confirmacao=False)

    resultado = cancelar_viagem(str(gestor.user.id), str(viagem_futura_agendada_com_motorista.id))

    assert resultado == {"message": "Viagem cancelada com sucesso", "alunos_notificados": 1}
    assert (
        _db.session.get(Viagem, viagem_futura_agendada_com_motorista.id).status
        == StatusViagem.CANCELADA
    )
    assert Notificacao.query.filter_by(usuario_id=aluno.user.id).count() == 1


def test_cancelar_viagem_de_outra_prefeitura_passa(
    _db, other_gestor, viagem_futura_agendada_com_motorista
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O guarda só checa o papel GESTOR. Sem checagem de prefeitura, um gestor
    cancela viagem de outra prefeitura.
    """
    resultado = cancelar_viagem(
        str(other_gestor.user.id), str(viagem_futura_agendada_com_motorista.id)
    )

    assert resultado["message"] == "Viagem cancelada com sucesso"


def test_cancelar_viagem_erro_no_commit_nao_vaza_texto_do_driver(
    _db, gestor, viagem_futura_agendada_com_motorista, monkeypatch
):
    """Corrigido: a falha do commit sobe crua e o handler genérico
    responde 500 "Erro interno do servidor", sem o texto do driver."""

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(viagens_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        cancelar_viagem(str(gestor.user.id), str(viagem_futura_agendada_com_motorista.id))


# ─── atualizar_localizacao ──────────────────────────────────────────────────


def test_atualizar_localizacao_recusa_gestor(_db, gestor, viagem_futura_iniciada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        atualizar_localizacao(
            str(gestor.user.id),
            str(viagem_futura_iniciada_com_motorista.id),
            {"latitude": -23.5, "longitude": -46.6},
        )

    assert exc.value.message == "Apenas motoristas podem enviar localização em tempo real"


def test_atualizar_localizacao_viagem_inexistente_404(_db, motorista):
    with pytest.raises(NotFoundError) as exc:
        atualizar_localizacao(
            str(motorista.user.id), str(uuid.uuid4()), {"latitude": -23.5, "longitude": -46.6}
        )

    assert exc.value.message == "Viagem não encontrada"


def test_atualizar_localizacao_viagem_agendada_400(
    _db, motorista, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        atualizar_localizacao(
            str(motorista.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"latitude": -23.5, "longitude": -46.6},
        )

    assert exc.value.message == "A viagem não está em andamento (Status: AGENDADA)"


def test_atualizar_localizacao_sem_pontos_grava_telemetria_e_avisa(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    resultado = atualizar_localizacao(
        str(motorista.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -23.5, "longitude": -46.6},
    )

    assert resultado == {
        "message": "Todos os pontos já foram visitados. Viagem quase concluída!",
        "observadores": False,
        "intervalo_sugerido_segundos": 30,
    }
    assert (
        TelemetriaViagem.query.filter_by(viagem_id=viagem_futura_iniciada_com_motorista.id).count()
        == 1
    )


def test_atualizar_localizacao_ponto_distante_nao_dispara_aviso(
    _db, motorista, prefeitura, viagem_futura_iniciada_com_motorista
):
    ponto_longe = _ponto(_db, prefeitura.id, -23.55, -46.63, "Longe")
    _db.session.add(
        ViagemPonto(
            viagem_id=viagem_futura_iniciada_com_motorista.id,
            ponto_id=ponto_longe.id,
            ordem=1,
            visitado=False,
        )
    )
    _db.session.commit()

    # ~1500 m ao sul do ponto: fora do raio de gatilho de 1000 m.
    resultado = atualizar_localizacao(
        str(motorista.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -23.5635, "longitude": -46.63},
    )

    assert resultado["message"] == "Localização atualizada silenciosamente com telemetria."
    assert 1400 < resultado["distancia_metros"] < 1600


def test_atualizar_localizacao_ponto_proximo_notifica_e_marca_aviso(
    _db, motorista, aluno, prefeitura, viagem_futura_iniciada_com_motorista
):
    ponto_perto = _ponto(_db, prefeitura.id, -23.55, -46.63, "Perto")
    vp = ViagemPonto(
        viagem_id=viagem_futura_iniciada_com_motorista.id,
        ponto_id=ponto_perto.id,
        ordem=1,
        visitado=False,
    )
    _db.session.add(vp)
    _db.session.commit()
    _confirmacao(
        _db,
        viagem_futura_iniciada_com_motorista,
        aluno.user.id,
        confirmacao=True,
        ponto_embarque_id=ponto_perto.id,
        embarcou=False,
    )

    # ~445 m ao sul do ponto: dentro do raio de gatilho de 1000 m.
    resultado = atualizar_localizacao(
        str(motorista.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -23.554, "longitude": -46.63},
    )

    assert "auto-checkin engatilhados" in resultado["message"]
    assert 400 < resultado["distancia_metros"] < 500
    _db.session.refresh(vp)
    assert vp.aviso_aproximacao_enviado is True
    assert Notificacao.query.filter_by(usuario_id=aluno.user.id).count() == 1


def test_atualizar_localizacao_motorista_alheio_atualiza_gps_de_viagem_de_outro(
    _db, other_motorista, viagem_futura_iniciada_com_motorista
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    A função checa apenas o papel MOTORISTA. Não compara
    ``viagem.motorista_id`` com o chamador, então qualquer motorista de
    qualquer prefeitura escreve o GPS de qualquer viagem em andamento.
    """
    atualizar_localizacao(
        str(other_motorista.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -10.0, "longitude": -40.0},
    )

    viagem = _db.session.get(Viagem, viagem_futura_iniciada_com_motorista.id)
    assert float(viagem.motorista_lat) == -10.0


# ─── obter_localizacao_onibus ───────────────────────────────────────────────


def test_obter_localizacao_usuario_inexistente_403(_db, viagem_futura_iniciada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        obter_localizacao_onibus(str(uuid.uuid4()), str(viagem_futura_iniciada_com_motorista.id))

    assert exc.value.message == "Acesso negado"


def test_obter_localizacao_viagem_inexistente_404(_db, motorista):
    with pytest.raises(NotFoundError) as exc:
        obter_localizacao_onibus(str(motorista.user.id), str(uuid.uuid4()))

    assert exc.value.message == "Viagem não encontrada"


def test_obter_localizacao_viagem_agendada_400(
    _db, motorista, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        obter_localizacao_onibus(
            str(motorista.user.id), str(viagem_futura_agendada_com_motorista.id)
        )

    assert (
        exc.value.message
        == "A localização do ônibus só está disponível enquanto a viagem está em andamento."
    )


def test_obter_localizacao_motorista_da_viagem_recebe_gps(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    agora = datetime.now(UTC)
    viagem_futura_iniciada_com_motorista.motorista_lat = -23.5
    viagem_futura_iniciada_com_motorista.motorista_lon = -46.6
    viagem_futura_iniciada_com_motorista.motorista_gps_hora = agora
    _db.session.commit()

    resultado = obter_localizacao_onibus(
        str(motorista.user.id), str(viagem_futura_iniciada_com_motorista.id)
    )

    assert resultado["latitude"] == -23.5
    assert resultado["longitude"] == -46.6
    assert resultado["atualizado_em"] is not None


def test_obter_localizacao_sem_gps_devolve_nulos(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    resultado = obter_localizacao_onibus(
        str(motorista.user.id), str(viagem_futura_iniciada_com_motorista.id)
    )

    assert resultado == {"latitude": None, "longitude": None, "atualizado_em": None}


def test_obter_localizacao_motorista_de_outra_viagem_403(
    _db, other_motorista, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        obter_localizacao_onibus(
            str(other_motorista.user.id), str(viagem_futura_iniciada_com_motorista.id)
        )

    assert exc.value.message == "Apenas o motorista desta viagem pode consultar a localização."


def test_obter_localizacao_aluno_nao_confirmado_403(
    _db, aluno, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        obter_localizacao_onibus(str(aluno.user.id), str(viagem_futura_iniciada_com_motorista.id))

    assert (
        exc.value.message
        == "Você precisa estar confirmado nesta viagem para ver a localização do ônibus."
    )


def test_obter_localizacao_aluno_confirmado_recebe_gps(
    _db, aluno, viagem_futura_iniciada_com_motorista
):
    _confirmacao(_db, viagem_futura_iniciada_com_motorista, aluno.user.id, confirmacao=True)

    resultado = obter_localizacao_onibus(
        str(aluno.user.id), str(viagem_futura_iniciada_com_motorista.id)
    )

    assert resultado["latitude"] is None


def test_obter_localizacao_gestor_403(_db, gestor, viagem_futura_iniciada_com_motorista):
    with pytest.raises(ForbiddenError) as exc:
        obter_localizacao_onibus(str(gestor.user.id), str(viagem_futura_iniciada_com_motorista.id))

    assert (
        exc.value.message
        == "Apenas alunos confirmados ou o motorista podem consultar a localização do ônibus."
    )


# ─── atualizar_localizacao_aluno ────────────────────────────────────────────


def test_atualizar_localizacao_aluno_recusa_motorista(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        atualizar_localizacao_aluno(
            str(motorista.user.id),
            str(viagem_futura_iniciada_com_motorista.id),
            {"latitude": -23.5, "longitude": -46.6},
        )

    assert exc.value.message == "Apenas alunos podem enviar a localização de embarque."


def test_atualizar_localizacao_aluno_viagem_inexistente_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        atualizar_localizacao_aluno(
            str(aluno.user.id), str(uuid.uuid4()), {"latitude": -23.5, "longitude": -46.6}
        )

    # Repare no ponto final: mensagem diferente das outras funções do módulo.
    assert exc.value.message == "Viagem não encontrada."


def test_atualizar_localizacao_aluno_viagem_agendada_400(
    _db, aluno, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ValidationError) as exc:
        atualizar_localizacao_aluno(
            str(aluno.user.id),
            str(viagem_futura_agendada_com_motorista.id),
            {"latitude": -23.5, "longitude": -46.6},
        )

    assert exc.value.message == "A viagem precisa de estar em andamento para rastrear o embarque."


def test_atualizar_localizacao_aluno_nao_confirmado_403(
    _db, aluno, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        atualizar_localizacao_aluno(
            str(aluno.user.id),
            str(viagem_futura_iniciada_com_motorista.id),
            {"latitude": -23.5, "longitude": -46.6},
        )

    assert exc.value.message == "O utilizador não está confirmado nesta viagem."


def test_atualizar_localizacao_aluno_grava_gps(_db, aluno, viagem_futura_iniciada_com_motorista):
    conf = _confirmacao(_db, viagem_futura_iniciada_com_motorista, aluno.user.id, confirmacao=True)

    resultado = atualizar_localizacao_aluno(
        str(aluno.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -23.5, "longitude": -46.6},
    )

    assert resultado["embarcou"] is False
    _db.session.refresh(conf)
    assert float(conf.aluno_lat) == -23.5
    assert conf.aluno_gps_hora is not None


def test_atualizar_localizacao_aluno_ja_embarcado_nao_grava(
    _db, aluno, viagem_futura_iniciada_com_motorista
):
    conf = _confirmacao(
        _db,
        viagem_futura_iniciada_com_motorista,
        aluno.user.id,
        confirmacao=True,
        embarcou=True,
    )

    resultado = atualizar_localizacao_aluno(
        str(aluno.user.id),
        str(viagem_futura_iniciada_com_motorista.id),
        {"latitude": -23.5, "longitude": -46.6},
    )

    assert resultado["embarcou"] is True
    _db.session.refresh(conf)
    assert conf.aluno_lat is None


# ─── gerar_viagens_periodo ──────────────────────────────────────────────────


def test_gerar_viagens_periodo_gera_um_dia_por_semana_no_intervalo(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo)

    total = gerar_viagens_periodo(str(gestor.user.id), dias_futuros=14)

    # 14 dias corridos cobrem o mesmo dia da semana duas vezes.
    assert total == 2
    assert Viagem.query.count() == 2


def test_gerar_viagens_periodo_engole_falha_e_devolve_zero(_db, gestor):
    """
    Papel errado faz cada dia levantar ForbiddenError dentro do laço; o
    ``except Exception`` registra em log e o total volta 0, sem propagar.
    """
    assert gerar_viagens_periodo(str(uuid.uuid4()), dias_futuros=3) == 0


# ─── envio de localização sob demanda ───────────────────────────────────────


def _post_gps(motorista, viagem):
    return atualizar_localizacao(
        str(motorista.user.id), str(viagem.id), {"latitude": -23.5, "longitude": -46.6}
    )


def test_localizacao_sob_demanda_ciclo_completo(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista
):
    viagem = viagem_futura_iniciada_com_motorista
    _confirmacao(_db, viagem, aluno.user.id, confirmacao=True)

    sem_consulta = _post_gps(motorista, viagem)
    assert sem_consulta["observadores"] is False
    assert sem_consulta["intervalo_sugerido_segundos"] == 30

    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))
    com_consulta = _post_gps(motorista, viagem)
    assert com_consulta["observadores"] is True
    assert com_consulta["intervalo_sugerido_segundos"] == 5

    viagem.localizacao_solicitada_em = datetime.now(UTC) - timedelta(seconds=46)
    _db.session.commit()
    expirada = _post_gps(motorista, viagem)
    assert expirada["observadores"] is False
    assert expirada["intervalo_sugerido_segundos"] == 30


def test_consulta_do_motorista_nao_conta_como_observador(
    _db, motorista, viagem_futura_iniciada_com_motorista
):
    viagem = viagem_futura_iniciada_com_motorista
    obter_localizacao_onibus(str(motorista.user.id), str(viagem.id))

    assert _post_gps(motorista, viagem)["observadores"] is False


# ─── push de demanda de localização ─────────────────────────────────────────


@pytest.fixture
def fcm_enviados(monkeypatch):
    enviados = []
    monkeypatch.setattr(
        "app.services.notificacao_service.messaging.send", lambda msg: enviados.append(msg)
    )
    return enviados


def _viagem_com_token(_db, motorista, aluno, viagem):
    motorista.user.fcm_token = "token-motorista"
    _confirmacao(_db, viagem, aluno.user.id, confirmacao=True)
    _db.session.commit()


def test_push_demanda_dispara_na_transicao_com_payload_exato(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, fcm_enviados
):
    viagem = viagem_futura_iniciada_com_motorista
    _viagem_com_token(_db, motorista, aluno, viagem)

    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    assert len(fcm_enviados) == 1
    msg = fcm_enviados[0]
    assert msg.token == "token-motorista"
    assert msg.notification is None
    assert msg.data == {"tipo": "demanda_localizacao", "viagem_id": str(viagem.id)}
    assert msg.android.priority == "high"
    assert msg.android.ttl == timedelta(seconds=30)
    assert msg.android.collapse_key == f"demanda_localizacao_{viagem.id}"


def test_push_demanda_nao_dispara_dentro_da_janela(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, fcm_enviados
):
    viagem = viagem_futura_iniciada_com_motorista
    _viagem_com_token(_db, motorista, aluno, viagem)

    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))
    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    assert len(fcm_enviados) == 1


def test_push_demanda_dispara_de_novo_apos_a_janela(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, fcm_enviados
):
    viagem = viagem_futura_iniciada_com_motorista
    _viagem_com_token(_db, motorista, aluno, viagem)
    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    viagem.localizacao_solicitada_em = datetime.now(UTC) - timedelta(seconds=46)
    _db.session.commit()
    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    assert len(fcm_enviados) == 2


def test_push_demanda_nao_dispara_para_consulta_do_motorista(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, fcm_enviados
):
    viagem = viagem_futura_iniciada_com_motorista
    _viagem_com_token(_db, motorista, aluno, viagem)

    obter_localizacao_onibus(str(motorista.user.id), str(viagem.id))

    assert fcm_enviados == []


def test_push_demanda_motorista_sem_token_nao_quebra(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, fcm_enviados
):
    viagem = viagem_futura_iniciada_com_motorista
    _confirmacao(_db, viagem, aluno.user.id, confirmacao=True)
    motorista.user.fcm_token = None
    _db.session.commit()

    obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    assert fcm_enviados == []


@pytest.mark.parametrize("erro", [RuntimeError("fcm fora"), ValueError("sem app")])
def test_push_demanda_falha_do_firebase_nao_derruba_o_get(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista, monkeypatch, erro
):
    viagem = viagem_futura_iniciada_com_motorista
    _viagem_com_token(_db, motorista, aluno, viagem)

    def falha(msg):
        raise erro

    monkeypatch.setattr("app.services.notificacao_service.messaging.send", falha)

    resultado = obter_localizacao_onibus(str(aluno.user.id), str(viagem.id))

    assert "latitude" in resultado
