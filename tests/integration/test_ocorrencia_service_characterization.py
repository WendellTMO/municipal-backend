"""Characterization tests for ``app/services/ocorrencia_service.py``.

Purpose: pin the CURRENT observable behaviour of every public method in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests: where the behaviour pinned here is a known
bug, the test name and comment say so. If one of these tests changes in
the SAME PR that changes the behaviour of
`ocorrencia_service.py`, the change was not a refactor.
"""

import uuid

import pytest
from sqlalchemy.exc import DataError

from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.enum import StatusOcorrencia, TipoOcorrencia
from app.models.notificacao import Notificacao
from app.models.ocorrencia import Ocorrencia
from app.models.rota import RotaAluno
from app.services import ocorrencia_service
from app.services.ocorrencia_service import OcorrenciaService

pytestmark = pytest.mark.integration


# ─── helpers ────────────────────────────────────────────────────────────────


def _ocorrencia(_db, autor_id, tipo=TipoOcorrencia.ATRASO, status=StatusOcorrencia.ABERTA):
    o = Ocorrencia(autor_id=autor_id, tipo=tipo, descricao="descrição", status=status)
    _db.session.add(o)
    _db.session.commit()
    return o


def _titulos_de(usuario_id):
    return [n.titulo for n in Notificacao.query.filter_by(usuario_id=usuario_id).all()]


# ─── criar: guardas ─────────────────────────────────────────────────────────


def test_criar_gestor_403(_db, gestor):
    with pytest.raises(ForbiddenError) as exc:
        OcorrenciaService.criar(str(gestor.user.id), {"tipo": "ATRASO"})

    assert str(exc.value) == "Apenas alunos e motoristas podem reportar ocorrências."


def test_criar_usuario_inexistente_403(_db):
    # Usuário ausente cai no mesmo ramo do papel errado: 403, não 404.
    with pytest.raises(ForbiddenError) as exc:
        OcorrenciaService.criar(str(uuid.uuid4()), {"tipo": "ATRASO"})

    assert str(exc.value) == "Apenas alunos e motoristas podem reportar ocorrências."


# ─── criar: validação do tipo ───────────────────────────────────────────────


def test_criar_sem_tipo_400(_db, aluno):
    with pytest.raises(ValidationError) as exc:
        OcorrenciaService.criar(str(aluno.user.id), {"descricao": "algo"})

    assert str(exc.value).startswith("Tipo inválido. Valores válidos:")


def test_criar_tipo_desconhecido_400(_db, aluno):
    with pytest.raises(ValidationError):
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "NAO_EXISTE"})


def test_criar_tipo_em_minusculas_400(_db, aluno):
    # `TipoOcorrencia[tipo_str]` resolve por nome e é sensível a caixa.
    with pytest.raises(ValidationError):
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "atraso"})


def test_criar_mensagem_de_tipo_invalido_lista_todos_os_valores(_db, aluno):
    with pytest.raises(ValidationError) as exc:
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "X"})

    for membro in TipoOcorrencia:
        assert membro.value in str(exc.value)


# ─── criar: caminho feliz ───────────────────────────────────────────────────


def test_criar_aluno_registra_ocorrencia_aberta(_db, aluno):
    ocorrencia = OcorrenciaService.criar(
        str(aluno.user.id), {"tipo": "ATRASO", "descricao": "Ônibus atrasou 40 minutos"}
    )

    assert ocorrencia.status == StatusOcorrencia.ABERTA
    assert ocorrencia.tipo == TipoOcorrencia.ATRASO
    assert ocorrencia.autor_id == aluno.user.id
    assert ocorrencia.descricao == "Ônibus atrasou 40 minutos"
    assert ocorrencia.viagem_id is None


def test_criar_motorista_tambem_pode(_db, motorista):
    ocorrencia = OcorrenciaService.criar(str(motorista.user.id), {"tipo": "SUPERLOTACAO"})

    assert ocorrencia.autor_id == motorista.user.id


def test_criar_sem_descricao_e_aceito(_db, aluno):
    ocorrencia = OcorrenciaService.criar(str(aluno.user.id), {"tipo": "OUTRO"})

    assert ocorrencia.descricao is None


def test_criar_com_viagem_valida_vincula(_db, aluno, viagem_futura_agendada_com_motorista):
    ocorrencia = OcorrenciaService.criar(
        str(aluno.user.id),
        {"tipo": "ATRASO", "viagem_id": str(viagem_futura_agendada_com_motorista.id)},
    )

    assert ocorrencia.viagem_id == viagem_futura_agendada_com_motorista.id


def test_criar_com_viagem_inexistente_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        OcorrenciaService.criar(
            str(aluno.user.id), {"tipo": "ATRASO", "viagem_id": str(uuid.uuid4())}
        )

    assert str(exc.value) == "Viagem não encontrada."


# ─── criar: notificação dos gestores ────────────────────────────────────────


def test_criar_notifica_o_gestor_da_prefeitura_do_autor(_db, aluno, gestor):
    OcorrenciaService.criar(str(aluno.user.id), {"tipo": "ATRASO", "descricao": "atrasou"})

    assert _titulos_de(gestor.user.id) == ["Nova Ocorrência: Atraso"]


def test_criar_nao_notifica_gestor_de_outra_prefeitura(_db, aluno, gestor, other_gestor):
    OcorrenciaService.criar(str(aluno.user.id), {"tipo": "ATRASO"})

    assert _titulos_de(gestor.user.id) == ["Nova Ocorrência: Atraso"]
    assert _titulos_de(other_gestor.user.id) == []


def test_criar_mensagem_da_notificacao_usa_nome_do_autor_e_descricao(_db, aluno, gestor):
    OcorrenciaService.criar(
        str(aluno.user.id), {"tipo": "COMPORTAMENTO", "descricao": "Motorista rude"}
    )

    notificacao = Notificacao.query.filter_by(usuario_id=gestor.user.id).one()
    assert notificacao.mensagem == f"{aluno.user.nome} reportou: Motorista rude"


def test_criar_sem_descricao_usa_o_rotulo_do_tipo_na_mensagem(_db, aluno, gestor):
    OcorrenciaService.criar(str(aluno.user.id), {"tipo": "CANCELAMENTO"})

    notificacao = Notificacao.query.filter_by(usuario_id=gestor.user.id).one()
    assert notificacao.mensagem == f"{aluno.user.nome} reportou: Cancelamento"


def test_criar_traduz_o_tipo_no_titulo_da_notificacao(_db, aluno, gestor):
    OcorrenciaService.criar(str(aluno.user.id), {"tipo": "SUPERLOTACAO"})

    assert _titulos_de(gestor.user.id) == ["Nova Ocorrência: Superlotação"]


# ─── criar: falhas conhecidas ───────────────────────────────────────────────


def test_criar_recusa_viagem_de_outra_prefeitura(
    _db, other_aluno, viagem_futura_agendada_com_motorista
):
    """Aluno de uma prefeitura não reporta ocorrência contra viagem de outra."""
    with pytest.raises(NotFoundError):
        OcorrenciaService.criar(
            str(other_aluno.user.id),
            {"tipo": "ATRASO", "viagem_id": str(viagem_futura_agendada_com_motorista.id)},
        )

    assert Ocorrencia.query.count() == 0


def test_criar_aceita_viagem_de_rota_em_que_o_aluno_de_fora_esta_inscrito(
    _db, other_aluno, rota, viagem_futura_agendada_com_motorista
):
    _db.session.add(RotaAluno(rota_id=rota.id, aluno_id=other_aluno.user.id))
    _db.session.commit()

    ocorrencia = OcorrenciaService.criar(
        str(other_aluno.user.id),
        {"tipo": "ATRASO", "viagem_id": str(viagem_futura_agendada_com_motorista.id)},
    )

    assert ocorrencia.viagem_id == viagem_futura_agendada_com_motorista.id


def test_criar_viagem_id_malformado_estoura_no_banco(_db, aluno):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O `viagem_id` vai cru para `db.session.get`. O Postgres levanta
    `DataError` e o handler genérico devolve 500, onde 400 caberia. Mesma
    família de bugs de validação de UUID que aparece nos demais serviços.
    """
    with pytest.raises(DataError):
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "ATRASO", "viagem_id": "nao-e-uuid"})


def test_criar_apperror_interno_passa_sem_ser_embrulhado(_db, aluno, monkeypatch):
    # O `except AppError` vem antes do `except Exception`, então um erro de
    # domínio levantado lá dentro (pela notificação, por exemplo) preserva o
    # próprio status em vez de virar 500.
    def notificacao_quebrada(_autor, _ocorrencia):
        raise NotFoundError("Gestor sumiu")

    monkeypatch.setattr(
        ocorrencia_service.OcorrenciaService, "_notificar_gestores", notificacao_quebrada
    )

    with pytest.raises(NotFoundError) as exc:
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "ATRASO"})

    assert exc.value.status_code == 404
    assert Ocorrencia.query.count() == 0


def test_criar_erro_no_commit_nao_vaza_texto_do_driver(_db, aluno, monkeypatch):
    """Corrigido: a falha do commit sobe crua e o handler genérico
    responde 500 "Erro interno do servidor", sem o texto do driver."""

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(ocorrencia_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        OcorrenciaService.criar(str(aluno.user.id), {"tipo": "ATRASO"})


# ─── listar ─────────────────────────────────────────────────────────────────


def test_listar_aluno_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        OcorrenciaService.listar(str(aluno.user.id))

    assert str(exc.value) == "Apenas gestores podem listar ocorrências."


def test_listar_motorista_403(_db, motorista):
    with pytest.raises(ForbiddenError) as exc:
        OcorrenciaService.listar(str(motorista.user.id))

    assert str(exc.value) == "Apenas gestores podem listar ocorrências."


def test_listar_usuario_inexistente_404(_db):
    # Aqui o guarda é o `_get_gestor_or_403`, que devolve 404 para usuário
    # ausente. O `criar`, no mesmo módulo, devolve 403 no mesmo cenário.
    with pytest.raises(NotFoundError) as exc:
        OcorrenciaService.listar(str(uuid.uuid4()))

    assert str(exc.value) == "Usuário não encontrado"


def test_listar_devolve_ocorrencias_da_prefeitura(_db, gestor, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    assert [o.id for o in OcorrenciaService.listar(str(gestor.user.id))] == [ocorrencia.id]


def test_listar_nao_vaza_ocorrencia_de_outra_prefeitura(_db, gestor, aluno, other_aluno):
    minha = _ocorrencia(_db, aluno.user.id)
    _ocorrencia(_db, other_aluno.user.id)

    assert [o.id for o in OcorrenciaService.listar(str(gestor.user.id))] == [minha.id]


def test_listar_ordena_da_mais_nova_para_a_mais_velha(_db, gestor, aluno):
    primeira = _ocorrencia(_db, aluno.user.id)
    segunda = _ocorrencia(_db, aluno.user.id)

    resultado = OcorrenciaService.listar(str(gestor.user.id))

    assert {o.id for o in resultado} == {primeira.id, segunda.id}
    assert resultado[0].created_at >= resultado[-1].created_at


def test_listar_filtra_por_status(_db, gestor, aluno):
    aberta = _ocorrencia(_db, aluno.user.id, status=StatusOcorrencia.ABERTA)
    _ocorrencia(_db, aluno.user.id, status=StatusOcorrencia.RESOLVIDA)

    resultado = OcorrenciaService.listar(str(gestor.user.id), status="ABERTA")

    assert [o.id for o in resultado] == [aberta.id]


def test_listar_status_invalido_da_400(_db, gestor, aluno):
    """Corrigido pelo PR #42: filtro de status inválido agora responde 400,
    em vez de devolver a lista inteira como se nenhum filtro tivesse sido
    pedido."""
    _ocorrencia(_db, aluno.user.id, status=StatusOcorrencia.ABERTA)
    _ocorrencia(_db, aluno.user.id, status=StatusOcorrencia.RESOLVIDA)

    with pytest.raises(ValidationError) as exc:
        OcorrenciaService.listar(str(gestor.user.id), status="NAO_EXISTE")

    assert "Status inválido" in str(exc.value)


def test_listar_sem_ocorrencias_devolve_lista_vazia(_db, gestor):
    assert OcorrenciaService.listar(str(gestor.user.id)) == []


# ─── resolver ───────────────────────────────────────────────────────────────


def test_resolver_aluno_403(_db, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    with pytest.raises(ForbiddenError) as exc:
        OcorrenciaService.resolver(str(aluno.user.id), str(ocorrencia.id))

    assert str(exc.value) == "Apenas gestores podem resolver ocorrências."


def test_resolver_usuario_inexistente_404(_db, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    with pytest.raises(NotFoundError) as exc:
        OcorrenciaService.resolver(str(uuid.uuid4()), str(ocorrencia.id))

    assert str(exc.value) == "Usuário não encontrado"


def test_resolver_marca_como_resolvida(_db, gestor, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    resultado = OcorrenciaService.resolver(str(gestor.user.id), str(ocorrencia.id))

    assert resultado.status == StatusOcorrencia.RESOLVIDA
    _db.session.expire_all()
    assert _db.session.get(Ocorrencia, ocorrencia.id).status == StatusOcorrencia.RESOLVIDA


def test_resolver_inexistente_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        OcorrenciaService.resolver(str(gestor.user.id), str(uuid.uuid4()))

    assert str(exc.value) == "Ocorrência não encontrada."


def test_resolver_ja_resolvida_400(_db, gestor, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id, status=StatusOcorrencia.RESOLVIDA)

    with pytest.raises(ValidationError) as exc:
        OcorrenciaService.resolver(str(gestor.user.id), str(ocorrencia.id))

    assert str(exc.value) == "Ocorrência já foi resolvida."


def test_resolver_gestor_de_outra_prefeitura_404(_db, other_gestor, aluno):
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    with pytest.raises(NotFoundError):
        OcorrenciaService.resolver(str(other_gestor.user.id), str(ocorrencia.id))

    _db.session.refresh(ocorrencia)
    assert ocorrencia.status == StatusOcorrencia.ABERTA


def test_resolver_gestor_da_prefeitura_da_viagem_resolve_ocorrencia_de_aluno_de_outra(
    _db, gestor, other_aluno, viagem_futura_agendada_com_motorista
):
    # Multi-tenant: aluno de outra prefeitura numa viagem desta prefeitura abre ocorrência
    # que o gestor da viagem precisa poder resolver.
    ocorrencia = _ocorrencia(_db, other_aluno.user.id)
    ocorrencia.viagem_id = viagem_futura_agendada_com_motorista.id
    _db.session.commit()

    resultado = OcorrenciaService.resolver(str(gestor.user.id), str(ocorrencia.id))

    assert resultado.status == StatusOcorrencia.RESOLVIDA


def test_resolver_erro_no_commit_nao_vaza_texto_do_driver(_db, gestor, aluno, monkeypatch):
    """Corrigido: a falha do commit sobe crua e o handler genérico
    responde 500 "Erro interno do servidor", sem o texto do driver."""
    ocorrencia = _ocorrencia(_db, aluno.user.id)

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(ocorrencia_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        OcorrenciaService.resolver(str(gestor.user.id), str(ocorrencia.id))
