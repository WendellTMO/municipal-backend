from datetime import date, timedelta
from datetime import time as hora
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ValidationError
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.viagem import Viagem
from app.services.viagens_service import (
    cancelar_viagem,
    confirmar_presenca_aluno,
    controlar_viagem,
    gerar_viagens_em_lote,
)
from tests.integration.test_viagens_service_characterization import (
    _horario_operando_em,
    _viagem,
)


def test_banco_recusa_duas_viagens_no_mesmo_horario_e_dia(_db, horario_rota):
    amanha = date.today() + timedelta(days=1)
    _viagem(_db, horario_rota, amanha)

    with pytest.raises(IntegrityError):
        _viagem(_db, horario_rota, amanha)
    _db.session.rollback()

    assert Viagem.query.filter_by(horario_rota_id=horario_rota.id).count() == 1


def test_viagens_sem_horario_nao_colidem_entre_si(_db):
    amanha = date.today() + timedelta(days=1)
    _viagem(_db, None, amanha)
    _viagem(_db, None, amanha)

    assert Viagem.query.filter_by(data=amanha).count() == 2


def test_lote_pula_so_a_viagem_que_colidiu_e_cria_as_outras(_db, gestor, rota):
    alvo = date.today() + timedelta(days=1)
    _horario_operando_em(_db, rota, alvo, hora=hora(7, 0))
    _horario_operando_em(_db, rota, alvo, hora=hora(17, 0))
    chamadas = []

    def popular_colidindo_na_primeira(viagem, rota_obj):
        chamadas.append(viagem)
        if len(chamadas) == 1:
            raise IntegrityError("insert", {}, Exception("uq_viagem_horario_data"))

    with patch(
        "app.services.viagens_service._popular_dados_da_viagem", popular_colidindo_na_primeira
    ):
        relatorio = gerar_viagens_em_lote(str(gestor.user.id), alvo)

    assert relatorio["viagens_criadas"] == 1
    assert Viagem.query.filter_by(data=alvo).count() == 1


def test_confirmar_presenca_em_viagem_finalizada_e_recusado(
    _db, aluno, rota_aluno, horario_rota
):
    viagem = _viagem(_db, horario_rota, date.today(), status=StatusViagem.FINALIZADA)

    with pytest.raises(ValidationError) as exc:
        confirmar_presenca_aluno(str(aluno.user.id), str(viagem.id), {"confirmacao": True})

    assert exc.value.message == "Esta viagem já terminou"


def _selects_da_viagem(executar):
    """Roda `executar` e devolve os SELECT na tabela viagem que usaram FOR UPDATE."""
    vistos: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        if "FROM viagem " in statement and "FOR UPDATE" in statement:
            vistos.append(statement)

    event.listen(db.engine, "before_cursor_execute", capturar)
    try:
        executar()
    finally:
        event.remove(db.engine, "before_cursor_execute", capturar)
    return vistos


def test_iniciar_trava_a_linha_da_viagem(_db, motorista, viagem_hoje_agendada_com_motorista):
    viagem = viagem_hoje_agendada_com_motorista

    vistos = _selects_da_viagem(
        lambda: controlar_viagem(str(motorista.user.id), str(viagem.id), {"acao": "INICIAR"})
    )

    assert len(vistos) == 1


def test_cancelar_trava_a_linha_da_viagem(_db, gestor, viagem_futura_agendada_com_motorista):
    viagem = viagem_futura_agendada_com_motorista

    vistos = _selects_da_viagem(lambda: cancelar_viagem(str(gestor.user.id), str(viagem.id)))

    assert len(vistos) == 1
