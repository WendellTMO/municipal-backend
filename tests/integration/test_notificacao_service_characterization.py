"""Characterization tests for ``app/services/notificacao_service.py``.

Purpose: pin the CURRENT observable behaviour of every public method in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests: where the behaviour pinned here is a known
bug, the test name and comment say so. If one of these tests changes in
the SAME PR that changes the behaviour of
`notificacao_service.py`, the change was not a refactor.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import DataError

from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.enum import StatusViagem
from app.models.notificacao import Notificacao
from app.models.rota import RotaAluno
from app.models.viagem import AlunosConfirmados, Viagem
from app.services import notificacao_service
from app.services.notificacao_service import NotificacaoService

pytestmark = pytest.mark.integration


# ─── helpers ────────────────────────────────────────────────────────────────


def _notificacao(_db, usuario_id, titulo="Aviso", mensagem="corpo"):
    n = Notificacao(usuario_id=usuario_id, titulo=titulo, mensagem=mensagem)
    _db.session.add(n)
    _db.session.commit()
    return n


def _confirmacao(_db, viagem_id, aluno_id, confirmacao):
    c = AlunosConfirmados(viagem_id=viagem_id, aluno_id=aluno_id, confirmacao=confirmacao)
    _db.session.add(c)
    _db.session.commit()
    return c


def _titulos_de(usuario_id):
    return [n.titulo for n in Notificacao.query.filter_by(usuario_id=usuario_id).all()]


# ─── notificar_por_gestor: guardas de papel ─────────────────────────────────


def test_notificar_usuario_inexistente_403_e_nao_404(_db):
    # CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui)
    # Usuário que não existe recebe 403 com o texto "Usuário não encontrado.",
    # misturando o código de autorização com a mensagem de ausência. Repare
    # também no ponto final, que os guardas de outros serviços não usam.
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(str(uuid.uuid4()), {})

    assert str(exc.value) == "Usuário não encontrado."
    assert exc.value.status_code == 403


def test_notificar_aluno_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(str(aluno.user.id), {})

    assert str(exc.value) == "Apenas gestores ou motoristas podem enviar comunicados."


def test_notificar_motorista_sem_viagem_id_403(_db, motorista):
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(motorista.user.id), {"titulo": "t", "mensagem": "m"}
        )

    assert str(exc.value) == "Motoristas devem informar viagem_id para enviar avisos."


def test_notificar_motorista_viagem_inexistente_403(_db, motorista):
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(motorista.user.id), {"viagem_id": str(uuid.uuid4())}
        )

    assert str(exc.value) == "Você só pode enviar avisos para viagens que você está conduzindo."


def test_notificar_motorista_de_outra_viagem_403(
    _db, other_motorista, viagem_futura_iniciada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(other_motorista.user.id),
            {"viagem_id": str(viagem_futura_iniciada_com_motorista.id)},
        )

    assert str(exc.value) == "Você só pode enviar avisos para viagens que você está conduzindo."


def test_notificar_motorista_viagem_agendada_403(
    _db, motorista, viagem_futura_agendada_com_motorista
):
    with pytest.raises(ForbiddenError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(motorista.user.id),
            {"viagem_id": str(viagem_futura_agendada_com_motorista.id)},
        )

    assert str(exc.value) == "Você só pode enviar avisos durante uma viagem em andamento."


def test_notificar_motorista_viagem_em_andamento_passa_no_guarda(
    _db, motorista, aluno, viagem_futura_iniciada_com_motorista
):
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, aluno.user.id, True)

    resultado = NotificacaoService.notificar_por_gestor(
        str(motorista.user.id),
        {
            "viagem_id": str(viagem_futura_iniciada_com_motorista.id),
            "titulo": "Atraso",
            "mensagem": "Vamos atrasar 10 minutos.",
        },
    )

    assert resultado == {"message": "Notificação enviada para 1 aluno(s) com sucesso."}
    assert _titulos_de(aluno.user.id) == ["Atraso"]


# ─── notificar_por_gestor: validação de payload ─────────────────────────────


def test_notificar_sem_titulo_400(_db, gestor, rota):
    with pytest.raises(ValidationError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"mensagem": "m", "rota_id": str(rota.id)}
        )

    assert str(exc.value) == "Título e mensagem são obrigatórios."


def test_notificar_sem_mensagem_400(_db, gestor, rota):
    with pytest.raises(ValidationError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "t", "rota_id": str(rota.id)}
        )

    assert str(exc.value) == "Título e mensagem são obrigatórios."


def test_notificar_titulo_vazio_cai_na_mesma_mensagem(_db, gestor, rota):
    # A checagem é `not titulo`, então string vazia é tratada como ausente.
    with pytest.raises(ValidationError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "", "mensagem": "m", "rota_id": str(rota.id)}
        )

    assert str(exc.value) == "Título e mensagem são obrigatórios."


def test_notificar_sem_alvo_400(_db, gestor):
    with pytest.raises(ValidationError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "t", "mensagem": "m"}
        )

    assert str(exc.value) == "Informe o ID de uma rota (rota_id) ou viagem (viagem_id)."


def test_notificar_rota_sem_alunos_404(_db, gestor, rota):
    with pytest.raises(NotFoundError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "t", "mensagem": "m", "rota_id": str(rota.id)}
        )

    assert str(exc.value) == "Nenhum aluno encontrado para receber este aviso."


def test_notificar_viagem_sem_confirmados_404(
    _db, gestor, aluno, viagem_futura_agendada_com_motorista
):
    # Aluno existe na viagem, mas com confirmacao=False: não conta como alvo.
    _confirmacao(_db, viagem_futura_agendada_com_motorista.id, aluno.user.id, False)

    with pytest.raises(NotFoundError) as exc:
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id),
            {
                "titulo": "t",
                "mensagem": "m",
                "viagem_id": str(viagem_futura_agendada_com_motorista.id),
            },
        )

    assert str(exc.value) == "Nenhum aluno encontrado para receber este aviso."


# ─── notificar_por_gestor: caminho feliz e seleção de alvo ──────────────────


def test_notificar_por_rota_atinge_todos_os_inscritos(_db, gestor, rota, aluno, other_aluno):
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=other_aluno.user.id))
    _db.session.commit()

    resultado = NotificacaoService.notificar_por_gestor(
        str(gestor.user.id),
        {"titulo": "Rota alterada", "mensagem": "Novo horário", "rota_id": str(rota.id)},
    )

    assert resultado == {"message": "Notificação enviada para 2 aluno(s) com sucesso."}
    assert _titulos_de(aluno.user.id) == ["Rota alterada"]
    assert _titulos_de(other_aluno.user.id) == ["Rota alterada"]


def test_notificar_por_viagem_atinge_so_os_confirmados(
    _db, gestor, aluno, other_aluno, viagem_futura_agendada_com_motorista
):
    _confirmacao(_db, viagem_futura_agendada_com_motorista.id, aluno.user.id, True)
    _confirmacao(_db, viagem_futura_agendada_com_motorista.id, other_aluno.user.id, False)

    resultado = NotificacaoService.notificar_por_gestor(
        str(gestor.user.id),
        {
            "titulo": "Aviso",
            "mensagem": "m",
            "viagem_id": str(viagem_futura_agendada_com_motorista.id),
        },
    )

    assert resultado == {"message": "Notificação enviada para 1 aluno(s) com sucesso."}
    assert _titulos_de(aluno.user.id) == ["Aviso"]
    assert _titulos_de(other_aluno.user.id) == []


def test_notificar_rota_id_tem_precedencia_sobre_viagem_id(
    _db, gestor, rota, aluno, other_aluno, viagem_futura_agendada_com_motorista
):
    # O `elif` faz `rota_id` vencer quando os dois vêm no payload: o aluno
    # confirmado na viagem não recebe nada se não estiver inscrito na rota.
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
    _db.session.commit()
    _confirmacao(_db, viagem_futura_agendada_com_motorista.id, other_aluno.user.id, True)

    resultado = NotificacaoService.notificar_por_gestor(
        str(gestor.user.id),
        {
            "titulo": "t",
            "mensagem": "m",
            "rota_id": str(rota.id),
            "viagem_id": str(viagem_futura_agendada_com_motorista.id),
        },
    )

    assert resultado == {"message": "Notificação enviada para 1 aluno(s) com sucesso."}
    assert _titulos_de(other_aluno.user.id) == []


def test_notificar_grava_corpo_e_data_de_envio(_db, gestor, rota, aluno):
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
    _db.session.commit()

    NotificacaoService.notificar_por_gestor(
        str(gestor.user.id),
        {"titulo": "Título", "mensagem": "Corpo da mensagem", "rota_id": str(rota.id)},
    )

    nova = Notificacao.query.filter_by(usuario_id=aluno.user.id).one()
    assert nova.mensagem == "Corpo da mensagem"
    assert nova.data_envio is not None
    assert nova.enviada is False


# ─── notificar_por_gestor: falhas conhecidas ────────────────────────────────


def test_notificar_gestor_de_outra_prefeitura_alcanca_rota_alheia(_db, other_gestor, rota, aluno):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O guarda só checa o papel. Nada compara a prefeitura do gestor com a da
    rota, então um gestor manda comunicado para os alunos de qualquer
    prefeitura.
    """
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
    _db.session.commit()

    resultado = NotificacaoService.notificar_por_gestor(
        str(other_gestor.user.id),
        {"titulo": "Invasivo", "mensagem": "m", "rota_id": str(rota.id)},
    )

    assert resultado == {"message": "Notificação enviada para 1 aluno(s) com sucesso."}
    assert _titulos_de(aluno.user.id) == ["Invasivo"]


def test_notificar_rota_id_malformado_estoura_no_banco(_db, gestor):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O `rota_id` vai cru para o filtro. O Postgres levanta `DataError` e o
    handler genérico devolve 500, onde 400 de campo inválido seria o esperado.
    Mesma família de bugs de validação de UUID que aparece nos demais serviços.
    """
    with pytest.raises(DataError):
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "t", "mensagem": "m", "rota_id": "nao-e-uuid"}
        )


def test_notificar_erro_no_commit_nao_vaza_texto_do_driver(_db, gestor, rota, aluno, monkeypatch):
    """Corrigido: a falha do commit sobe crua e o handler genérico
    responde 500 "Erro interno do servidor", sem o texto do driver."""
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=aluno.user.id))
    _db.session.commit()

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(notificacao_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        NotificacaoService.notificar_por_gestor(
            str(gestor.user.id), {"titulo": "t", "mensagem": "m", "rota_id": str(rota.id)}
        )


# ─── listar_notificacoes ────────────────────────────────────────────────────


def test_listar_notificacoes_devolve_as_do_usuario(_db, aluno, other_aluno):
    minha = _notificacao(_db, aluno.user.id, titulo="Minha")
    _notificacao(_db, other_aluno.user.id, titulo="Alheia")

    resultado = NotificacaoService.listar_notificacoes(str(aluno.user.id))

    assert [n.id for n in resultado] == [minha.id]


def test_listar_notificacoes_ordena_da_mais_nova_para_a_mais_velha(_db, aluno):
    primeira = _notificacao(_db, aluno.user.id, titulo="Primeira")
    segunda = _notificacao(_db, aluno.user.id, titulo="Segunda")

    resultado = NotificacaoService.listar_notificacoes(str(aluno.user.id))

    assert {n.id for n in resultado} == {primeira.id, segunda.id}
    assert resultado[0].created_at >= resultado[-1].created_at


def test_listar_notificacoes_usuario_inexistente_devolve_lista_vazia(_db):
    # Sem checagem de existência nem de papel: id desconhecido devolve [].
    assert NotificacaoService.listar_notificacoes(str(uuid.uuid4())) == []


def test_listar_notificacoes_nao_tem_gate_de_papel(_db, gestor):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    A função não carrega o usuário nem checa papel. Filtra só por
    `usuario_id`, então quem conseguir passar um id alheio lê a caixa de
    entrada daquele usuário. Hoje o id vem do JWT no controller, o que
    esconde a lacuna atrás da borda.
    """
    alheia = _notificacao(_db, gestor.user.id, titulo="Do gestor")

    assert [n.id for n in NotificacaoService.listar_notificacoes(str(gestor.user.id))] == [
        alheia.id
    ]


# ─── marcar_lida ────────────────────────────────────────────────────────────


def test_marcar_lida_marca_e_devolve_mensagem(_db, aluno):
    notificacao = _notificacao(_db, aluno.user.id)

    resultado = NotificacaoService.marcar_lida(str(aluno.user.id), str(notificacao.id))

    assert resultado == {"message": "Notificação marcada como lida."}
    _db.session.refresh(notificacao)
    assert notificacao.enviada is True


def test_marcar_lida_usa_a_coluna_enviada_como_flag_de_leitura(_db, aluno):
    # CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui)
    # Não existe coluna `lida`. O serviço reaproveita `enviada`, que pelo nome
    # descreve o envio, para registrar a leitura. Renomear é migração.
    notificacao = _notificacao(_db, aluno.user.id)
    assert notificacao.enviada is False

    NotificacaoService.marcar_lida(str(aluno.user.id), str(notificacao.id))

    _db.session.refresh(notificacao)
    assert notificacao.enviada is True


def test_marcar_lida_inexistente_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        NotificacaoService.marcar_lida(str(aluno.user.id), str(uuid.uuid4()))

    assert str(exc.value) == "Notificação não encontrada."


def test_marcar_lida_de_outro_usuario_404_e_nao_403(_db, aluno, other_aluno):
    # Esconder a existência com 404 no lugar de 403 parece proposital aqui.
    alheia = _notificacao(_db, other_aluno.user.id)

    with pytest.raises(NotFoundError) as exc:
        NotificacaoService.marcar_lida(str(aluno.user.id), str(alheia.id))

    assert str(exc.value) == "Notificação não encontrada."
    _db.session.refresh(alheia)
    assert alheia.enviada is False


def test_excluir_remove_a_notificacao(_db, aluno):
    notificacao = _notificacao(_db, aluno.user.id)
    notificacao_id = notificacao.id

    resultado = NotificacaoService.excluir(str(aluno.user.id), str(notificacao_id))

    assert resultado == {"message": "Notificação excluída."}
    assert _db.session.get(Notificacao, notificacao_id) is None


def test_excluir_de_outro_usuario_404_e_mantem_a_notificacao(_db, aluno, other_aluno):
    alheia = _notificacao(_db, other_aluno.user.id)

    with pytest.raises(NotFoundError):
        NotificacaoService.excluir(str(aluno.user.id), str(alheia.id))

    assert _db.session.get(Notificacao, alheia.id) is not None


def test_marcar_lida_erro_no_commit_nao_vaza_texto_do_driver(_db, aluno, monkeypatch):
    """Corrigido: mesma troca do `notificar_por_gestor`."""
    notificacao = _notificacao(_db, aluno.user.id)

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(notificacao_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        NotificacaoService.marcar_lida(str(aluno.user.id), str(notificacao.id))


# ─── notificar_alunos_viagem_iniciada ───────────────────────────────────────


def test_viagem_iniciada_notifica_so_os_confirmados(
    _db, aluno, other_aluno, viagem_futura_iniciada_com_motorista
):
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, aluno.user.id, True)
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, other_aluno.user.id, False)

    NotificacaoService.notificar_alunos_viagem_iniciada(
        str(viagem_futura_iniciada_com_motorista.id)
    )

    assert _titulos_de(aluno.user.id) == ["🚌 Viagem Iniciada!"]
    assert _titulos_de(other_aluno.user.id) == []


def test_viagem_iniciada_persiste_as_notificacoes(_db, aluno, viagem_futura_iniciada_com_motorista):
    # O rollback depois da chamada separa commit de objeto só pendente na
    # sessão: sem commit, o autoflush faria a query passar do mesmo jeito.
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, aluno.user.id, True)

    NotificacaoService.notificar_alunos_viagem_iniciada(
        str(viagem_futura_iniciada_com_motorista.id)
    )
    _db.session.rollback()

    assert _titulos_de(aluno.user.id) == ["🚌 Viagem Iniciada!"]


def test_viagem_iniciada_grava_o_corpo_fixo(_db, aluno, viagem_futura_iniciada_com_motorista):
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, aluno.user.id, True)

    NotificacaoService.notificar_alunos_viagem_iniciada(
        str(viagem_futura_iniciada_com_motorista.id)
    )

    nova = Notificacao.query.filter_by(usuario_id=aluno.user.id).one()
    assert nova.mensagem == (
        "O motorista acabou de iniciar a rota. Acompanhe o trajeto no aplicativo!"
    )


def test_viagem_iniciada_sem_confirmados_nao_cria_nada(_db, viagem_futura_iniciada_com_motorista):
    NotificacaoService.notificar_alunos_viagem_iniciada(
        str(viagem_futura_iniciada_com_motorista.id)
    )

    assert Notificacao.query.count() == 0


def test_viagem_iniciada_nao_valida_a_viagem(_db):
    # Id de viagem que não existe não levanta nada: o filtro só devolve zero
    # confirmados e a função retorna em silêncio.
    assert NotificacaoService.notificar_alunos_viagem_iniciada(str(uuid.uuid4())) is None


def test_viagem_iniciada_engole_a_falha_e_nao_propaga(
    _db, aluno, viagem_futura_iniciada_com_motorista, monkeypatch
):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O `except Exception` registra em log e retorna normalmente. Quem chama,
    `controlar_viagem` na ação INICIAR, não tem como saber que nenhum aluno
    foi avisado: a viagem inicia e a API responde 200.
    """
    _confirmacao(_db, viagem_futura_iniciada_com_motorista.id, aluno.user.id, True)

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(notificacao_service.db.session, "commit", falha_generica)

    assert (
        NotificacaoService.notificar_alunos_viagem_iniciada(
            str(viagem_futura_iniciada_com_motorista.id)
        )
        is None
    )


# ─── _criar_notificacao_interna: guarda do push ─────────────────────────────


def test_push_so_e_tentado_quando_ha_fcm_token(_db, aluno, monkeypatch):
    # Sem `fcm_token` o Firebase nunca é chamado. É o que mantém a suíte
    # offline sem precisar de mock do SDK.
    chamadas = []
    monkeypatch.setattr(notificacao_service.messaging, "send", lambda m: chamadas.append(m) or "id")

    NotificacaoService._criar_notificacao_interna(str(aluno.user.id), "t", "m")
    _db.session.commit()

    assert chamadas == []


def test_push_e_enviado_quando_o_usuario_tem_fcm_token(_db, aluno, monkeypatch):
    # Com token, o SDK é chamado uma vez, com título e corpo da notificação.
    aluno.user.fcm_token = "token-de-teste"
    _db.session.commit()
    enviadas = []
    monkeypatch.setattr(
        notificacao_service.messaging, "send", lambda m: enviadas.append(m) or "msg-id"
    )

    NotificacaoService._criar_notificacao_interna(str(aluno.user.id), "Título", "Corpo")
    _db.session.commit()

    assert len(enviadas) == 1
    assert enviadas[0].token == "token-de-teste"
    assert enviadas[0].notification.title == "Título"
    assert enviadas[0].notification.body == "Corpo"


def test_falha_do_push_nao_impede_a_notificacao_interna(_db, aluno, monkeypatch):
    # O envio fica dentro de try/except: o registro no banco sobrevive a uma
    # queda do Firebase.
    aluno.user.fcm_token = "token-de-teste"
    _db.session.commit()

    def push_quebrado(_mensagem):
        raise RuntimeError("firebase fora do ar")

    monkeypatch.setattr(notificacao_service.messaging, "send", push_quebrado)

    NotificacaoService._criar_notificacao_interna(str(aluno.user.id), "Sobrevive", "m")
    _db.session.commit()

    assert _titulos_de(aluno.user.id) == ["Sobrevive"]


def test_viagem_finalizada_nao_e_condicao_para_notificar_inicio(
    _db, aluno, horario_rota, motorista
):
    # A função não olha o status da viagem, só as confirmações.
    viagem = Viagem(
        data=date.today() + timedelta(days=1),
        horario_rota_id=horario_rota.id,
        status=StatusViagem.FINALIZADA,
        motorista_id=motorista.user.id,
    )
    _db.session.add(viagem)
    _db.session.commit()
    _confirmacao(_db, viagem.id, aluno.user.id, True)

    NotificacaoService.notificar_alunos_viagem_iniciada(str(viagem.id))

    assert _titulos_de(aluno.user.id) == ["🚌 Viagem Iniciada!"]
