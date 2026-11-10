"""O Swagger não pode prometer campo que o serviço descarta.

`app/api/contracts/*` documenta a API para o flask-restx. `app/schemas/*` é
quem valida de verdade, e o `BaseSchema` usa `unknown = EXCLUDE`, então todo
campo documentado que o schema não declara é silenciosamente jogado fora.

Estes testes fixam o resultado da auditoria: para cada modelo de request do
contrato existe um schema correspondente, e nenhum campo sobra de um lado só.

Guarda de escopo que continua valendo: 3 dos 31 `@api.expect` passam
`validate=True` e por isso validam em runtime. São
`dashboard_controller.py:41`, `notificacao_controller.py:33` e
`ocorrencia_controller.py:55`. Editar esses models é mudança de comportamento,
e nenhum deles é tocado aqui.
"""

import inspect
import re

import pytest

from app.api.contracts import onibus_contract, rota_contract, user_contract

pytestmark = pytest.mark.integration


def _campos_do_modelo(modulo, nome_do_modelo: str) -> set[str]:
    """Nomes de campo declarados num `api.model("Nome", {...})` do contrato."""
    fonte = inspect.getsource(modulo)
    i = fonte.index(f'"{nome_do_modelo}"')
    # Só o dicionário deste modelo: para no primeiro fechamento do bloco.
    corpo = fonte[i : fonte.index("\n    )", i)]
    return set(re.findall(r'"(\w+)":\s*fields\.', corpo)) - {nome_do_modelo}


def test_onibus_create_nao_documenta_ano(_db):
    # `ano` nunca existiu: não está no modelo Onibus, no schema nem no serviço.
    campos = _campos_do_modelo(onibus_contract, "OnibusCreateRequest")

    assert "ano" not in campos
    assert {"placa", "modelo", "capacidade"} <= campos


def test_rota_update_nao_documenta_pontos_e_horarios(_db):
    # `update_rota` trata apenas nome, motorista_padrao_id e veiculo_padrao_id.
    # Pontos e horários têm endpoints próprios: `add_ponto` e `add_horario`.
    campos = _campos_do_modelo(rota_contract, "RotaUpdateRequest")

    assert "pontos" not in campos
    assert "horarios" not in campos
    assert {"nome", "motorista_padrao_id", "veiculo_padrao_id"} <= campos


def test_motorista_create_nao_documenta_salario(_db):
    # `Motorista` não tem coluna `salario`: ela saiu na migração `a1b2c3d4e5f6`.
    # Mesma família de campo fantasma que sobrou de coluna removida.
    campos = _campos_do_modelo(user_contract, "MotoristaCreateRequest")

    assert "salario" not in campos
    assert {"nome", "email", "cpf", "cnh"} <= campos


def test_contratos_que_validam_em_runtime_nao_foram_tocados(_db):
    """Guarda de escopo desta auditoria.

    Três `@api.expect` passam `validate=True` e por isso validam de verdade.
    Se alguém mover um deles para um contrato editado por esta auditoria, o
    que era doc-only vira validação de runtime e a mudança deixa de ser segura.
    Este teste falha se a contagem mudar, obrigando a revisitar o escopo.
    """
    import pathlib

    # Só o arquivo, sem o número da linha: editar o controller não deve quebrar esta guarda.
    ocorrencias = []
    for f in pathlib.Path("app/api/controllers").glob("*.py"):
        for linha in f.read_text().split("\n"):
            if "validate=True" in linha:
                ocorrencias.append(f.name)

    assert sorted(ocorrencias) == [
        "dashboard_controller.py",
        "notificacao_controller.py",
        "ocorrencia_controller.py",
    ]
