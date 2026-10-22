"""
Characterization tests for ``app/services/rotas_service.py``.

Purpose: pin the CURRENT observable behaviour of every public function in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests. Where the behaviour pinned here is a known
bug, the test name and comment say so. When that behaviour is fixed, the
corresponding test must be updated in the SAME PR that changes it.
"""

import uuid

import pytest
from sqlalchemy.exc import DataError

from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.enum import DiaDaSemana, SentidoViagem, UserRole
from app.models.geo import Ponto
from app.models.rota import DiasOperacao, HorarioRota, Rota, RotaAluno, RotaPonto
from app.services.rotas_service import (
    add_horario,
    add_ponto,
    create_rota,
    delete_rota,
    gerenciar_inscricao_aluno,
    get_by_id,
    get_horarios,
    get_pontos_by_rota,
    list_all_rotas,
    list_my_rotas,
    update_rota,
)

pytestmark = pytest.mark.integration


# ─── helpers ───────────────────────────────────────────────────────────────────


def novo_uuid() -> str:
    return str(uuid.uuid4())


def cria_ponto(_db, prefeitura_id, apelido="Ponto teste", ordem=None):
    p = Ponto(
        prefeitura_id=prefeitura_id,
        apelido=apelido,
        latitude=-7.21,
        longitude=-35.88,
    )
    _db.session.add(p)
    _db.session.commit()
    return p


# ─── list_all_rotas ────────────────────────────────────────────────────────────


def test_list_all_rotas_retorna_rotas_da_prefeitura(_db, gestor, rota):
    resultado = list_all_rotas(str(gestor.user.id))

    assert [r.id for r in resultado] == [rota.id]


def test_list_all_rotas_nao_vaza_rota_de_outra_prefeitura(_db, other_gestor, rota):
    resultado = list_all_rotas(str(other_gestor.user.id))

    assert resultado == []


def test_list_all_rotas_uuid_invalido_da_validation_error(_db, gestor):
    with pytest.raises(ValidationError):
        list_all_rotas("nao-e-uuid")


def test_list_all_rotas_usuario_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        list_all_rotas(novo_uuid())

    assert exc.value.status_code == 404
    assert str(exc.value) == "Usuário não encontrado"


# ─── list_my_rotas ─────────────────────────────────────────────────────────────


def test_list_my_rotas_aluno_ve_apenas_rotas_inscritas(_db, aluno, rota, rota_aluno):
    resultado = list_my_rotas(str(aluno.user.id))

    assert [r.id for r in resultado] == [rota.id]


def test_list_my_rotas_aluno_sem_inscricao_ve_lista_vazia(_db, aluno, rota):
    resultado = list_my_rotas(str(aluno.user.id))

    assert resultado == []


def test_list_my_rotas_motorista_ve_rotas_onde_e_padrao(_db, motorista, rota):
    resultado = list_my_rotas(str(motorista.user.id))

    assert [r.id for r in resultado] == [rota.id]


def test_list_my_rotas_gestor_ve_todas_as_rotas_da_prefeitura(_db, gestor, rota):
    resultado = list_my_rotas(str(gestor.user.id))

    assert [r.id for r in resultado] == [rota.id]


def test_list_my_rotas_usuario_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError):
        list_my_rotas(novo_uuid())


def test_list_my_rotas_uuid_invalido_da_400(_db, gestor):
    """Corrigido: `list_my_rotas` passou a chamar `validate_uuid`, como a
    vizinha `list_all_rotas` já fazia. As duas agora tratam o mesmo argumento
    do mesmo jeito, e id malformado vira 400 em vez do 500 do `DataError`."""
    with pytest.raises(ValidationError):
        list_my_rotas("nao-e-uuid")


# ─── gerenciar_inscricao_aluno ─────────────────────────────────────────────────


def test_inscricao_aluno_inscreve_com_sucesso(_db, aluno, rota):
    resultado = gerenciar_inscricao_aluno(str(aluno.user.id), str(rota.id), {"acao": "inscrever"})

    assert resultado == {"message": "Inscrição realizada com sucesso"}
    assert RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=aluno.user.id).count() == 1


def test_inscricao_aluno_duplicada_e_idempotente(_db, aluno, rota, rota_aluno):
    resultado = gerenciar_inscricao_aluno(str(aluno.user.id), str(rota.id), {"acao": "inscrever"})

    assert resultado == {"message": "Aluno já inscrito nesta rota"}
    assert RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=aluno.user.id).count() == 1


def test_desinscricao_aluno_remove_vinculo(_db, aluno, rota, rota_aluno):
    resultado = gerenciar_inscricao_aluno(
        str(aluno.user.id), str(rota.id), {"acao": "desinscrever"}
    )

    assert resultado == {"message": "Inscrição removida com sucesso"}
    assert RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=aluno.user.id).count() == 0


def test_desinscricao_sem_inscricao_da_404(_db, aluno, rota):
    with pytest.raises(NotFoundError) as exc:
        gerenciar_inscricao_aluno(str(aluno.user.id), str(rota.id), {"acao": "desinscrever"})

    assert str(exc.value) == "Aluno não está inscrito nesta rota"


def test_inscricao_gestor_recebe_403(_db, gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        gerenciar_inscricao_aluno(str(gestor.user.id), str(rota.id), {"acao": "inscrever"})

    assert exc.value.status_code == 403
    assert str(exc.value) == "Apenas alunos podem se inscrever"


def test_inscricao_usuario_inexistente_recebe_403_e_nao_404(_db, aluno, rota):
    """A checagem de papel vem antes da de existência, então some vira 403."""
    with pytest.raises(ForbiddenError):
        gerenciar_inscricao_aluno(novo_uuid(), str(rota.id), {"acao": "inscrever"})


def test_inscricao_rota_inexistente_da_404(_db, aluno):
    with pytest.raises(NotFoundError) as exc:
        gerenciar_inscricao_aluno(str(aluno.user.id), novo_uuid(), {"acao": "inscrever"})

    assert str(exc.value) == "Rota não encontrada"


def test_inscricao_cross_tenant_bloqueada(_db, other_aluno, rota):
    with pytest.raises(ForbiddenError) as exc:
        gerenciar_inscricao_aluno(str(other_aluno.user.id), str(rota.id), {"acao": "inscrever"})

    assert str(exc.value) == "Acesso negado a esta rota"


def test_inscricao_acao_invalida_da_400(_db, aluno, rota):
    with pytest.raises(ValidationError) as exc:
        gerenciar_inscricao_aluno(str(aluno.user.id), str(rota.id), {"acao": "voar"})

    assert str(exc.value) == "Ação inválida. Use 'inscrever' ou 'desinscrever'."


def test_inscricao_sem_acao_da_400(_db, aluno, rota):
    with pytest.raises(ValidationError):
        gerenciar_inscricao_aluno(str(aluno.user.id), str(rota.id), {})


def test_inscricao_uuid_invalido_da_400(_db, aluno):
    with pytest.raises(ValidationError):
        gerenciar_inscricao_aluno(str(aluno.user.id), "nao-e-uuid", {"acao": "inscrever"})


# ─── create_rota ───────────────────────────────────────────────────────────────


def test_create_rota_minima_pelo_gestor(_db, gestor):
    rota = create_rota(str(gestor.user.id), {"nome": "Rota Centro"})

    assert rota.nome == "Rota Centro"
    assert rota.prefeitura_id == gestor.user.prefeitura_id
    assert rota.motorista_padrao_id is None
    assert Rota.query.get(rota.id) is not None


def test_create_rota_motorista_se_autoatribui(_db, motorista):
    rota = create_rota(str(motorista.user.id), {"nome": "Rota do motorista"})

    assert rota.motorista_padrao_id == motorista.user.id


def test_create_rota_motorista_respeita_motorista_padrao_explicito(_db, motorista, prefeitura):
    from tests.factories.user_factory import MotoristaFactory

    outro = MotoristaFactory(prefeitura_id=prefeitura.id)
    _db.session.add(outro)
    _db.session.commit()

    rota = create_rota(
        str(motorista.user.id),
        {"nome": "Rota", "motorista_padrao_id": str(outro.id)},
    )

    assert str(rota.motorista_padrao_id) == str(outro.id)


def test_create_rota_aluno_recebe_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        create_rota(str(aluno.user.id), {"nome": "Rota"})

    assert str(exc.value) == "Permissão negada"


def test_create_rota_usuario_inexistente_recebe_403(_db, gestor):
    with pytest.raises(ForbiddenError):
        create_rota(novo_uuid(), {"nome": "Rota"})


def test_create_rota_sem_nome_da_400(_db, gestor):
    with pytest.raises(ValidationError) as exc:
        create_rota(str(gestor.user.id), {"nome": ""})

    assert str(exc.value) == "Nome da rota é obrigatório"


def test_create_rota_com_ponto_existente(_db, gestor, ponto):
    rota = create_rota(
        str(gestor.user.id),
        {"nome": "Rota", "pontos": [{"ponto_id": str(ponto.id), "ordem": 3}]},
    )

    vinculos = RotaPonto.query.filter_by(rota_id=rota.id).all()
    assert len(vinculos) == 1
    assert vinculos[0].ordem == 3


def test_create_rota_com_coordenadas_cria_ponto_novo(_db, gestor):
    rota = create_rota(
        str(gestor.user.id),
        {
            "nome": "Rota",
            "pontos": [{"latitude": -7.21, "longitude": -35.88, "apelido": "Praça", "ordem": 1}],
        },
    )

    vinculo = RotaPonto.query.filter_by(rota_id=rota.id).one()
    assert vinculo.ponto.apelido == "Praça"
    assert vinculo.ponto.prefeitura_id == gestor.user.prefeitura_id


def test_create_rota_ponto_inexistente_da_404(_db, gestor):
    # B51: antes o ponto inexistente era pulado com log e a rota nascia sem
    # ele. Agora o `create_rota` recusa igual ao `add_ponto`.
    with pytest.raises(NotFoundError) as exc:
        create_rota(
            str(gestor.user.id),
            {"nome": "Rota", "pontos": [{"ponto_id": str(uuid.uuid4()), "ordem": 1}]},
        )

    assert "não encontrado" in str(exc.value)
    assert Rota.query.filter_by(nome="Rota").count() == 0


def test_create_rota_recusa_ponto_de_outra_prefeitura(_db, gestor, other_prefeitura):
    """O PR #39 fez o `create_rota` parar de vincular ponto de outra
    prefeitura, escolhendo pular em silêncio. Esse PR desfez o empate com o
    `add_ponto`, que levanta: agora os dois recusam do mesmo jeito e a rota
    inteira é abortada.
    """
    ponto_alheio = cria_ponto(_db, other_prefeitura.id, apelido="Alheio")

    with pytest.raises(ForbiddenError) as exc:
        create_rota(
            str(gestor.user.id),
            {"nome": "Rota", "pontos": [{"ponto_id": str(ponto_alheio.id), "ordem": 1}]},
        )

    assert "pertence a outra prefeitura" in str(exc.value)
    assert Rota.query.filter_by(nome="Rota").count() == 0


def test_create_rota_com_horarios_e_dias(_db, gestor):
    rota = create_rota(
        str(gestor.user.id),
        {
            "nome": "Rota",
            "horarios": [{"horario_saida": "07:00", "sentido": "IDA", "dias": ["SEG", "TER"]}],
        },
    )

    horario = HorarioRota.query.filter_by(rota_id=rota.id).one()
    assert horario.sentido == SentidoViagem.IDA
    assert {d.dia for d in horario.dias} == {DiaDaSemana.SEG, DiaDaSemana.TER}


def test_create_rota_descarta_dia_invalido_sem_erro(_db, gestor):
    rota = create_rota(
        str(gestor.user.id),
        {
            "nome": "Rota",
            "horarios": [{"horario_saida": "07:00", "sentido": "IDA", "dias": ["SEG", "SEGUNDA"]}],
        },
    )

    horario = HorarioRota.query.filter_by(rota_id=rota.id).one()
    assert [d.dia for d in horario.dias] == [DiaDaSemana.SEG]


def test_create_rota_sentido_invalido_sobe_como_data_error(_db, gestor):
    """Continua sendo 500 para o cliente, agora pelo handler genérico em vez do
    `except Exception` do serviço, e sem o SQL embutido na resposta.

    Repare na diferença para o `add_horario`: lá o serviço faz
    `DiaDaSemana(dia_str)` e o enum levanta `ValueError` antes do banco. Aqui o
    `sentido` vai cru para a coluna, então quem recusa é o Postgres, com
    `DataError`. Virar 400 nos dois exige validar na borda.
    """
    with pytest.raises(DataError):
        create_rota(
            str(gestor.user.id),
            {
                "nome": "Rota",
                "horarios": [{"horario_saida": "07:00", "sentido": "PARA_CIMA", "dias": []}],
            },
        )

    assert Rota.query.filter_by(nome="Rota").count() == 0


# ─── add_ponto ─────────────────────────────────────────────────────────────────


def test_add_ponto_vincula_ponto_existente(_db, gestor, rota, ponto):
    add_ponto(str(gestor.user.id), str(rota.id), {"pontos": [{"ponto_id": str(ponto.id)}]})

    vinculo = RotaPonto.query.filter_by(rota_id=rota.id).one()
    assert vinculo.ponto_id == ponto.id
    assert vinculo.ordem == 1  # ordem default


def test_add_ponto_cria_ponto_por_coordenadas(_db, gestor, rota):
    add_ponto(
        str(gestor.user.id),
        str(rota.id),
        {"pontos": [{"nome": "Escola", "latitude": -7.21, "longitude": -35.88, "ordem": 2}]},
    )

    vinculo = RotaPonto.query.filter_by(rota_id=rota.id).one()
    assert vinculo.ponto.apelido == "Escola"
    assert vinculo.ordem == 2


def test_add_ponto_apaga_os_pontos_anteriores_da_rota(_db, gestor, rota, ponto, rota_ponto):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    O nome ``add_ponto`` promete adicionar. A implementação apaga todos os
    ``RotaPonto`` da rota e recria a lista a partir do payload. Um cliente que
    mande um ponto só perde os demais.
    """
    outro = cria_ponto(_db, rota.prefeitura_id, apelido="Novo")

    add_ponto(str(gestor.user.id), str(rota.id), {"pontos": [{"ponto_id": str(outro.id)}]})

    vinculos = RotaPonto.query.filter_by(rota_id=rota.id).all()
    # FALHA: substitui em vez de adicionar, o ponto anterior sumiu.
    assert [v.ponto_id for v in vinculos] == [outro.id]


def test_add_ponto_motorista_tem_permissao(_db, motorista, rota, ponto):
    add_ponto(str(motorista.user.id), str(rota.id), {"pontos": [{"ponto_id": str(ponto.id)}]})

    assert RotaPonto.query.filter_by(rota_id=rota.id).count() == 1


def test_add_ponto_aluno_recebe_403(_db, aluno, rota, ponto):
    with pytest.raises(ForbiddenError) as exc:
        add_ponto(str(aluno.user.id), str(rota.id), {"pontos": [{"ponto_id": str(ponto.id)}]})

    assert str(exc.value) == "Permissão negada"


def test_add_ponto_rota_inexistente_da_404(_db, gestor, ponto):
    with pytest.raises(NotFoundError) as exc:
        add_ponto(str(gestor.user.id), novo_uuid(), {"pontos": [{"ponto_id": str(ponto.id)}]})

    assert str(exc.value) == "Rota não encontrada"


def test_add_ponto_cross_tenant_bloqueado(_db, other_gestor, rota, ponto):
    with pytest.raises(ForbiddenError) as exc:
        add_ponto(
            str(other_gestor.user.id), str(rota.id), {"pontos": [{"ponto_id": str(ponto.id)}]}
        )

    assert str(exc.value) == "Acesso negado"


def test_add_ponto_lista_vazia_da_400(_db, gestor, rota):
    with pytest.raises(ValidationError) as exc:
        add_ponto(str(gestor.user.id), str(rota.id), {"pontos": []})

    assert str(exc.value) == "A rota deve conter pelo menos um ponto válido"


def test_add_ponto_de_outra_prefeitura_agora_da_403(_db, gestor, rota, other_prefeitura):
    # Antes o ponto alheio era descartado em silêncio e a API
    # respondia sucesso. Agora a substituição inteira é abortada.
    ponto_alheio = cria_ponto(_db, other_prefeitura.id, apelido="Alheio")

    with pytest.raises(ForbiddenError) as exc:
        add_ponto(
            str(gestor.user.id),
            str(rota.id),
            {"pontos": [{"ponto_id": str(ponto_alheio.id), "ordem": 1}]},
        )

    assert "pertence a outra prefeitura" in str(exc.value)


def test_add_ponto_sem_nome_ou_coordenada_agora_da_400(_db, gestor, rota):
    # Ponto novo incompleto era descartado em silêncio.
    with pytest.raises(ValidationError) as exc:
        add_ponto(str(gestor.user.id), str(rota.id), {"pontos": [{"latitude": -7.21}]})

    assert str(exc.value) == "Ponto novo exige nome, latitude e longitude"


def test_add_horario_cria_horario_e_dias(_db, gestor, rota):
    horario = add_horario(
        str(gestor.user.id),
        str(rota.id),
        {"horario_saida": "07:30", "sentido": "IDA", "dias": ["SEG", "QUA"]},
    )

    assert horario.sentido == SentidoViagem.IDA
    assert DiasOperacao.query.filter_by(horario_rota_id=horario.id).count() == 2


def test_add_horario_motorista_recebe_403(_db, motorista, rota):
    """
    CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui).

    ``create_rota`` deixa o motorista criar rota com grade de horários junto.
    ``add_horario`` recusa o mesmo motorista. A regra de papel muda conforme o
    caminho usado para escrever o mesmo dado.
    """
    with pytest.raises(ForbiddenError) as exc:
        add_horario(
            str(motorista.user.id),
            str(rota.id),
            {"horario_saida": "07:30", "sentido": "IDA", "dias": ["SEG"]},
        )

    assert str(exc.value) == "Apenas gestores gerenciam horários"


def test_add_horario_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError):
        add_horario(
            str(gestor.user.id),
            novo_uuid(),
            {"horario_saida": "07:30", "sentido": "IDA", "dias": ["SEG"]},
        )


def test_add_horario_cross_tenant_bloqueado(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        add_horario(
            str(other_gestor.user.id),
            str(rota.id),
            {"horario_saida": "07:30", "sentido": "IDA", "dias": ["SEG"]},
        )

    assert str(exc.value) == "Acesso negado"


def test_add_horario_sem_dias_da_400(_db, gestor, rota):
    with pytest.raises(ValidationError) as exc:
        add_horario(str(gestor.user.id), str(rota.id), {"horario_saida": "07:30", "sentido": "IDA"})

    assert str(exc.value) == "Selecione pelo menos um dia da semana"


def test_add_horario_dia_invalido_sobe_como_value_error(_db, gestor, rota):
    """Mesma troca do `create_rota`: o `ValueError` do enum sobe cru."""
    with pytest.raises(ValueError):
        add_horario(
            str(gestor.user.id),
            str(rota.id),
            {"horario_saida": "07:30", "sentido": "IDA", "dias": ["SEGUNDA"]},
        )

    assert HorarioRota.query.filter_by(rota_id=rota.id).count() == 0


# ─── get_horarios ──────────────────────────────────────────────────────────────


def test_get_horarios_retorna_grade_da_rota(_db, gestor, rota, horario_rota):
    resultado = get_horarios(str(gestor.user.id), str(rota.id))

    assert [h.id for h in resultado] == [horario_rota.id]


def test_get_horarios_usuario_inexistente_da_404(_db, rota):
    with pytest.raises(NotFoundError) as exc:
        get_horarios(novo_uuid(), str(rota.id))

    assert str(exc.value) == "Usuário não encontrado"


def test_get_horarios_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        get_horarios(str(gestor.user.id), novo_uuid())

    assert str(exc.value) == "Rota não encontrada"


def test_get_horarios_cross_tenant_bloqueado_para_gestor(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        get_horarios(str(other_gestor.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"


def test_get_horarios_cross_tenant_bloqueado_para_motorista(_db, other_motorista, rota):
    with pytest.raises(ForbiddenError):
        get_horarios(str(other_motorista.user.id), str(rota.id))


def test_get_horarios_aluno_de_outra_prefeitura_agora_da_403(_db, other_aluno, rota, horario_rota):
    # O guarda deixava ALUNO passar porque só comparava a
    # prefeitura para GESTOR e MOTORISTA. Agora vale para todos os papéis.
    with pytest.raises(ForbiddenError) as exc:
        get_horarios(str(other_aluno.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"


def test_get_by_id_retorna_rota(_db, gestor, rota):
    assert get_by_id(str(gestor.user.id), str(rota.id)).id == rota.id


def test_get_by_id_usuario_inexistente_da_404(_db, rota):
    with pytest.raises(NotFoundError) as exc:
        get_by_id(novo_uuid(), str(rota.id))

    assert str(exc.value) == "Usuário não encontrado"


def test_get_by_id_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        get_by_id(str(gestor.user.id), novo_uuid())

    assert str(exc.value) == "Rota não encontrada"


def test_get_by_id_cross_tenant_bloqueado_para_gestor(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        get_by_id(str(other_gestor.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"


def test_get_by_id_aluno_de_outra_prefeitura_agora_da_403(_db, other_aluno, rota):
    # Mesmo guarda do `get_horarios`.
    with pytest.raises(ForbiddenError) as exc:
        get_by_id(str(other_aluno.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"


def test_update_rota_altera_nome(_db, gestor, rota):
    atualizada = update_rota(str(gestor.user.id), str(rota.id), {"nome": "Rota nova"})

    assert atualizada.nome == "Rota nova"
    assert Rota.query.get(rota.id).nome == "Rota nova"


def test_update_rota_altera_motorista_e_veiculo(_db, gestor, rota):
    update_rota(
        str(gestor.user.id),
        str(rota.id),
        {"motorista_padrao_id": None, "veiculo_padrao_id": None},
    )

    persistida = Rota.query.get(rota.id)
    assert persistida.motorista_padrao_id is None
    assert persistida.veiculo_padrao_id is None


def test_update_rota_ignora_campos_ausentes(_db, gestor, rota):
    nome_original = rota.nome

    update_rota(str(gestor.user.id), str(rota.id), {})

    assert Rota.query.get(rota.id).nome == nome_original


def test_update_rota_motorista_recebe_403(_db, motorista, rota):
    """Ao contrário de ``create_rota`` e ``add_ponto``, aqui só GESTOR passa."""
    with pytest.raises(ForbiddenError) as exc:
        update_rota(str(motorista.user.id), str(rota.id), {"nome": "x"})

    assert str(exc.value) == "Permissão negada"


def test_update_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        update_rota(str(gestor.user.id), novo_uuid(), {"nome": "x"})

    assert str(exc.value) == "Rota não encontrada"


def test_update_rota_cross_tenant_bloqueado(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        update_rota(str(other_gestor.user.id), str(rota.id), {"nome": "x"})

    assert str(exc.value) == "Acesso negado"
    assert Rota.query.get(rota.id).nome != "x"


def test_update_rota_uuid_invalido_da_400(_db, gestor):
    with pytest.raises(ValidationError):
        update_rota(str(gestor.user.id), "nao-e-uuid", {"nome": "x"})


# ─── delete_rota ───────────────────────────────────────────────────────────────


def test_delete_rota_remove_a_rota(_db, gestor, rota):
    delete_rota(str(gestor.user.id), str(rota.id))

    assert Rota.query.get(rota.id) is None


def test_delete_rota_remove_grade_e_inscricoes_em_cascata(
    _db, gestor, rota, horario_rota, dia_operacao, rota_aluno, rota_ponto
):
    delete_rota(str(gestor.user.id), str(rota.id))

    assert HorarioRota.query.filter_by(rota_id=rota.id).count() == 0
    assert DiasOperacao.query.filter_by(horario_rota_id=horario_rota.id).count() == 0
    assert RotaAluno.query.filter_by(rota_id=rota.id).count() == 0
    assert RotaPonto.query.filter_by(rota_id=rota.id).count() == 0


def test_delete_rota_motorista_recebe_403(_db, motorista, rota):
    with pytest.raises(ForbiddenError) as exc:
        delete_rota(str(motorista.user.id), str(rota.id))

    assert str(exc.value) == "Permissão negada"
    assert Rota.query.get(rota.id) is not None


def test_delete_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        delete_rota(str(gestor.user.id), novo_uuid())

    assert str(exc.value) == "Rota não encontrada"


def test_delete_rota_cross_tenant_bloqueado(_db, other_gestor, rota):
    with pytest.raises(ForbiddenError) as exc:
        delete_rota(str(other_gestor.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"
    assert Rota.query.get(rota.id) is not None


def test_delete_rota_uuid_invalido_da_400(_db, gestor):
    with pytest.raises(ValidationError):
        delete_rota(str(gestor.user.id), "nao-e-uuid")


# ─── get_pontos_by_rota ────────────────────────────────────────────────────────


def test_get_pontos_by_rota_retorna_pontos_ordenados(_db, gestor, rota, ponto):
    segundo = cria_ponto(_db, rota.prefeitura_id, apelido="Segundo")
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=segundo.id, ordem=2))
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=ponto.id, ordem=1))
    _db.session.commit()

    resultado = get_pontos_by_rota(str(gestor.user.id), str(rota.id))

    assert [p["ordem"] for p in resultado] == [1, 2]
    assert set(resultado[0]) == {"id", "apelido", "latitude", "longitude", "ordem", "instituicao"}
    assert resultado[0]["id"] == str(ponto.id)


def test_get_pontos_by_rota_sem_pontos_retorna_lista_vazia(_db, gestor, rota):
    assert get_pontos_by_rota(str(gestor.user.id), str(rota.id)) == []


def test_get_pontos_by_rota_usuario_inexistente_da_404(_db, rota):
    with pytest.raises(NotFoundError) as exc:
        get_pontos_by_rota(novo_uuid(), str(rota.id))

    assert str(exc.value) == "Usuário não encontrado"


def test_get_pontos_by_rota_inexistente_da_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        get_pontos_by_rota(str(gestor.user.id), novo_uuid())

    assert str(exc.value) == "Rota não encontrada"


def test_get_pontos_by_rota_agora_checa_tenant(_db, other_gestor, rota, ponto, rota_ponto):
    # Esta era a pior das três: nenhuma checagem de prefeitura,
    # e o `rota_id` é parâmetro de path, então qualquer autenticado lia as
    # coordenadas de embarque de qualquer rota.
    with pytest.raises(ForbiddenError) as exc:
        get_pontos_by_rota(str(other_gestor.user.id), str(rota.id))

    assert str(exc.value) == "Acesso negado"


def test_papeis_aceitos_por_funcao_de_escrita(_db, gestor, motorista, aluno, rota, ponto):
    """
    Resumo executável de quem escreve o quê hoje. Três regras diferentes no
    mesmo módulo, uma por função. Serve de rede para a unificação futura.
    """
    assert gestor.user.role == UserRole.GESTOR
    assert motorista.user.role == UserRole.MOTORISTA
    assert aluno.user.role == UserRole.ALUNO

    # create_rota e add_ponto: GESTOR e MOTORISTA.
    create_rota(str(motorista.user.id), {"nome": "ok"})
    add_ponto(str(motorista.user.id), str(rota.id), {"pontos": [{"ponto_id": str(ponto.id)}]})

    # add_horario, update_rota e delete_rota: só GESTOR.
    for chamada in (
        lambda: add_horario(
            str(motorista.user.id),
            str(rota.id),
            {"horario_saida": "07:00", "sentido": "IDA", "dias": ["SEG"]},
        ),
        lambda: update_rota(str(motorista.user.id), str(rota.id), {"nome": "x"}),
        lambda: delete_rota(str(motorista.user.id), str(rota.id)),
    ):
        with pytest.raises(ForbiddenError):
            chamada()

    # gerenciar_inscricao_aluno: só ALUNO.
    with pytest.raises(ForbiddenError):
        gerenciar_inscricao_aluno(str(gestor.user.id), str(rota.id), {"acao": "inscrever"})
