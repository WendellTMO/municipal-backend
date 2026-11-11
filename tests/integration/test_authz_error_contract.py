"""Trava (pin) do contrato de erro de autorização — status, code e message.

Por que este arquivo existe
---------------------------
As checagens de permissão hoje estão espalhadas pelos services e cada uma
escreve a sua própria mensagem à mão. O mesmo "não pode" sai como
"Acesso negado", "Acesso negado a este recurso" ou "Permissão negada"
dependendo do arquivo que o desenvolvedor abriu naquele dia.

A centralização futura da autorização em ``app/core/authz.py`` vai
inevitavelmente reescrever essas mensagens. Este teste é uma
*characterization test*: ele fotografa o que o cliente HTTP recebe HOJE, de
forma que o diff dessa mudança mostre exatamente quais respostas mudaram, em
vez de a mudança passar silenciosamente para o app.

Como usar quando essa centralização (ou qualquer mexida em autorização) quebrar isto
------------------------------------------------------------------------------------
A falha NÃO significa "o código está errado". Significa "o contrato visível
mudou, confirme se era intencional". Se for intencional, atualize a tabela
no mesmo commit — assim o histórico registra a quebra de contrato de API.
"""

from __future__ import annotations

import pytest
from flask_jwt_extended import create_access_token

# UUID sintaticamente válido que nunca existe no banco: exercita o caminho
# "token bem formado, usuário sumiu" (usuário deletado / banco recriado).
GHOST_USER_ID = "02d895f4-35f2-49d4-818f-63fc75e8c48b"


@pytest.fixture()
def ghost_headers(app):
    with app.app_context():
        token = create_access_token(identity=GHOST_USER_ID)
    return {"Authorization": f"Bearer {token}"}


# (caso, ator, método, path, status, code, message)
#
# `path` aceita os placeholders {rota_id}, {ponto_id} e {onibus_id}.
AUTHZ_CONTRACT = [
    # --- Gate de papel: "só gestor faz isso" -------------------------------
    # Todos passam por user_service._get_gestor_or_403, cada um com a sua
    # própria string. É este conjunto que a futura centralização tende a uniformizar.
    (
        "listar usuários exige gestor",
        "aluno",
        "get",
        "/v1/users",
        403,
        "FORBIDDEN",
        "Apenas gestores podem listar usuários",
    ),
    (
        "listar alunos exige gestor (aluno)",
        "aluno",
        "get",
        "/v1/alunos/",
        403,
        "FORBIDDEN",
        "Apenas gestores podem listar alunos",
    ),
    (
        "listar alunos exige gestor (motorista)",
        "motorista",
        "get",
        "/v1/alunos/",
        403,
        "FORBIDDEN",
        "Apenas gestores podem listar alunos",
    ),
    (
        "histórico de viagens exige gestor",
        "aluno",
        "get",
        "/v1/viagens/",
        403,
        "FORBIDDEN",
        "Apenas gestores podem acessar o histórico completo",
    ),
    (
        "relatório operacional exige gestor",
        "aluno",
        "get",
        "/v1/dashboard/relatorios/periodo?data_inicio=2026-01-01&data_fim=2026-02-01",
        403,
        "FORBIDDEN",
        "Apenas gestores podem visualizar relatórios operacionais",
    ),
    # --- Gate de papel escrito à mão ("Permissão negada") ------------------
    # Mesma intenção do bloco acima, mas sem passar por _get_gestor_or_403 —
    # por isso a mensagem é genérica e não diz o que faltou.
    (
        "criar ponto exige gestor",
        "aluno",
        "post",
        "/v1/pontos/",
        403,
        "FORBIDDEN",
        "Permissão negada",
    ),
    (
        "criar rota exige gestor",
        "aluno",
        "post",
        "/v1/rotas/",
        403,
        "FORBIDDEN",
        "Permissão negada",
    ),
    # --- Isolamento entre prefeituras ("Acesso negado") --------------------
    # Ator é gestor legítimo, mas de OUTRA prefeitura. Note que o recurso
    # existe: a resposta é 403 e não 404, ou seja, a API confirma a
    # existência do ID para quem não pode vê-lo.
    (
        "ler rota de outra prefeitura",
        "other_gestor",
        "get",
        "/v1/rotas/{rota_id}",
        403,
        "FORBIDDEN",
        "Acesso negado",
    ),
    (
        "editar rota de outra prefeitura",
        "other_gestor",
        "put",
        "/v1/rotas/{rota_id}",
        403,
        "FORBIDDEN",
        "Acesso negado",
    ),
    (
        "ler ponto de outra prefeitura",
        "other_gestor",
        "get",
        "/v1/pontos/{ponto_id}",
        403,
        "FORBIDDEN",
        "Acesso negado",
    ),
    (
        "apagar ponto de outra prefeitura",
        "other_gestor",
        "delete",
        "/v1/pontos/{ponto_id}",
        403,
        "FORBIDDEN",
        "Acesso negado",
    ),
    (
        "ler ônibus de outra prefeitura",
        "other_gestor",
        "get",
        "/v1/onibus/{onibus_id}",
        403,
        "FORBIDDEN",
        "Acesso negado a este recurso",
    ),
    # --- Token válido, usuário inexistente ---------------------------------
    # 404 (e não 401), porque a checagem é feita no service e não no JWT.
    (
        "usuário sumido — pontos",
        "ghost",
        "get",
        "/v1/pontos/",
        404,
        "NOT_FOUND",
        "Usuário não encontrado",
    ),
    (
        "usuário sumido — rotas",
        "ghost",
        "get",
        "/v1/rotas/",
        404,
        "NOT_FOUND",
        "Usuário não encontrado",
    ),
    (
        "usuário sumido — ônibus",
        "ghost",
        "get",
        "/v1/onibus/",
        404,
        "NOT_FOUND",
        "Usuário não encontrado",
    ),
    (
        "usuário sumido — perfil próprio",
        "ghost",
        "get",
        "/v1/users/me",
        404,
        "NOT_FOUND",
        "Usuário não encontrado",
    ),
]

# Bodies mínimos para as rotas de escrita, só para passar da desserialização
# e chegar na checagem de permissão — que é o que estamos medindo.
BODIES = {
    ("post", "/v1/pontos/"): {"nome": "Ponto", "latitude": -7.21, "longitude": -35.90},
    ("post", "/v1/rotas/"): {"nome": "Rota"},
    ("put", "/v1/rotas/{rota_id}"): {"nome": "Rota"},
}


@pytest.mark.integration
def test_authz_error_contract(
    client, gestor, other_gestor, aluno, motorista, ghost_headers, rota, ponto, onibus
):
    """Percorre a tabela inteira e reporta TODAS as divergências de uma vez.

    Escolha deliberada: um único teste em vez de parametrize. Quando essas
    mensagens forem centralizadas, o desenvolvedor quer ver a lista completa do
    que mudou numa falha só, e não consertar 16 testes vermelhos um a um.
    """
    headers_por_ator = {
        "gestor": gestor.headers,
        "other_gestor": other_gestor.headers,
        "aluno": aluno.headers,
        "motorista": motorista.headers,
        "ghost": ghost_headers,
    }
    ids = {"rota_id": rota.id, "ponto_id": ponto.id, "onibus_id": onibus.id}

    divergencias = []
    for caso, ator, metodo, path_tpl, status, code, message in AUTHZ_CONTRACT:
        path = path_tpl.format(**ids)
        body = BODIES.get((metodo, path_tpl))
        kwargs = {"json": body} if body is not None else {}

        resposta = getattr(client, metodo)(path, headers=headers_por_ator[ator], **kwargs)
        corpo = resposta.get_json() or {}
        erro = corpo.get("error", {}) if isinstance(corpo, dict) else {}

        obtido = (resposta.status_code, erro.get("code"), erro.get("message"))
        esperado = (status, code, message)
        if obtido != esperado:
            divergencias.append(
                f"  {caso}\n"
                f"    {metodo.upper()} {path} como {ator}\n"
                f"    esperado: {esperado}\n"
                f"    obtido:   {obtido}"
            )

    assert not divergencias, (
        "O contrato de erro de autorização mudou em "
        f"{len(divergencias)} de {len(AUTHZ_CONTRACT)} casos.\n"
        "Se a mudança foi intencional, atualize AUTHZ_CONTRACT no mesmo commit.\n\n"
        + "\n".join(divergencias)
    )


@pytest.mark.integration
def test_authz_falhas_conhecidas(client, aluno):
    """Fotografa buracos REAIS de autorização que existem hoje.

    ATENÇÃO: ao contrário do teste acima, o que está travado aqui NÃO é o
    comportamento desejado. São falhas confirmadas, deixadas fora do escopo
    deste PR (que é só de caracterização, sem mudança de comportamento).

    Quando cada uma for corrigida, este teste vai quebrar — e isso é o
    sinal de sucesso. Remova o bloco correspondente junto com a correção.
    """
    # Envelope de erro inconsistente: validação via reqparse do flask_restx
    #    (@api.expect(parser, validate=True)) responde no formato do próprio
    #    restx e não passa pelos @app.errorhandler. O cliente recebe 400 sem
    #    `error.code`, quebrando o contrato garantido por test_error_contract.
    r = client.get("/v1/dashboard/relatorios/periodo", headers=aluno.headers)
    assert r.status_code == 400
    corpo = r.get_json() or {}
    assert "error" not in corpo, "corrigido? este endpoint agora usa o envelope padrão"
    assert corpo["message"] == "Input payload validation failed"
