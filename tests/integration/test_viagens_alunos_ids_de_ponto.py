"""GET /v1/viagens/minhas devolve os ids dos pontos de cada aluno da viagem."""

import pytest

from app.models.viagem import AlunosConfirmados

pytestmark = pytest.mark.integration


def test_aluno_com_ponto_devolve_ids(
    _db, motorista, aluno, ponto, viagem_futura_agendada_com_motorista
):
    _db.session.add(
        AlunosConfirmados(
            viagem_id=viagem_futura_agendada_com_motorista.id,
            aluno_id=aluno.user.id,
            confirmacao=True,
            ponto_embarque_id=ponto.id,
            ponto_destino_id=ponto.id,
        )
    )
    _db.session.commit()

    resp = motorista.client.get("/v1/viagens/minhas")

    assert resp.status_code == 200
    item = resp.get_json()["items"][0]["alunos"][0]
    assert item["ponto_embarque_id"] == str(ponto.id)
    assert item["ponto_destino_id"] == str(ponto.id)


def test_aluno_confirmado_sem_ponto_devolve_ids_null(
    _db, motorista, aluno, viagem_futura_agendada_com_motorista
):
    _db.session.add(
        AlunosConfirmados(
            viagem_id=viagem_futura_agendada_com_motorista.id,
            aluno_id=aluno.user.id,
            confirmacao=True,
        )
    )
    _db.session.commit()

    resp = motorista.client.get("/v1/viagens/minhas")

    assert resp.status_code == 200
    item = resp.get_json()["items"][0]["alunos"][0]
    assert item["ponto_embarque_id"] is None
    assert item["ponto_destino_id"] is None
