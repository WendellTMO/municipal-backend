"""Telemetria de uso: recebe lote, limpa o que não pode ficar, exige login e apaga o antigo."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.telemetria import EventoTelemetria

CONTEXTO = {
    "sessao_id": "sessao-abc-123",
    "versao_app": "1.0.4-beta (29899425)",
    "plataforma": "android",
    "dispositivo": "realme RMX3941",
    "versao_so": "Android 16 (API 36)",
}


def _enviar(actor, eventos, contexto=None):
    return actor.client.post(
        "/v1/telemetria", json={"contexto": CONTEXTO if contexto is None else contexto, "eventos": eventos}
    )


def test_grava_evento_valido_com_papel_e_contexto(aluno, _db):
    agora_ms = int(datetime.now(UTC).timestamp() * 1000)
    r = _enviar(aluno, [{"tipo": "tela", "nome": "DashboardAluno", "props": {"ms": 340}, "em": agora_ms}])
    # nome em maiúsculas é recusado: o app manda em minúsculas
    assert r.get_json() == {"aceitos": 0, "descartados": 1}

    r = _enviar(aluno, [{"tipo": "tela", "nome": "dashboard_aluno", "props": {"ms": 340}, "em": agora_ms}])
    assert r.status_code == 200
    assert r.get_json() == {"aceitos": 1, "descartados": 0}

    evento = EventoTelemetria.query.one()
    assert evento.usuario_id == aluno.user.id
    assert evento.papel == "ALUNO"
    assert evento.sessao_id == "sessao-abc-123"
    assert evento.dispositivo == "realme RMX3941"
    assert evento.props == {"ms": 340}


def test_descarta_tipo_e_nome_invalidos_sem_derrubar_o_lote(aluno):
    r = _enviar(
        aluno,
        [
            {"tipo": "tela", "nome": "inicio"},
            {"tipo": "espionagem", "nome": "x"},
            {"tipo": "acao", "nome": "tem espaço"},
            "nao-e-objeto",
            {"tipo": "erro", "nome": "js_erro"},
        ],
    )
    assert r.get_json() == {"aceitos": 2, "descartados": 3}


def test_props_so_aceita_valor_simples_e_corta_o_resto(aluno):
    props = {
        "ok": True,
        "ms": 12.5,
        "tela": "x" * 500,
        "aninhado": {"a": 1},
        "lista": [1, 2],
        "Chave Ruim": 1,
    }
    _enviar(aluno, [{"tipo": "api", "nome": "get:/viagens", "props": props}])
    evento = EventoTelemetria.query.one()
    assert evento.props["ok"] is True
    assert evento.props["ms"] == 12.5
    assert len(evento.props["tela"]) == 120
    assert "aninhado" not in evento.props and "lista" not in evento.props and "Chave Ruim" not in evento.props


def test_hora_absurda_do_aparelho_vira_a_hora_de_chegada(aluno):
    em_2001 = 1_000_000_000_000
    _enviar(aluno, [{"tipo": "tela", "nome": "inicio", "em": em_2001}])
    evento = EventoTelemetria.query.one()
    assert evento.ocorrido_em > datetime.now(UTC) - timedelta(minutes=1)


def test_lote_grande_demais_e_recusado(aluno):
    eventos = [{"tipo": "tela", "nome": "inicio"}] * 51
    assert _enviar(aluno, eventos).status_code == 400
    assert EventoTelemetria.query.count() == 0


def test_exige_login_e_sessao(client, aluno):
    r = client.post("/v1/telemetria", json={"contexto": CONTEXTO, "eventos": []})
    assert r.status_code == 401
    assert _enviar(aluno, [{"tipo": "tela", "nome": "inicio"}], contexto={}).status_code == 400
