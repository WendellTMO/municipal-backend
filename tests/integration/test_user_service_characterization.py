"""Characterization tests for ``app/services/user_service.py``.

Purpose: pin the CURRENT observable behaviour of every public function in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests: where the behaviour pinned here is a known
bug, the test name and comment say so. If one of these tests changes in
the SAME PR that changes the behaviour of
`user_service.py`, the change was not a refactor.
"""

import uuid

import pytest
from werkzeug.security import check_password_hash

from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.models.enum import UserRole, UserStatus
from app.models.user import Motorista, User
from app.services import user_service
from app.services.user_service import (
    change_password,
    create_aluno_account,
    create_motorista,
    delete_motorista,
    get_all_users,
    get_motoristas_by_municipio,
    get_user_by_id,
    update_fcm_token,
    update_profile,
    update_user,
)

pytestmark = pytest.mark.integration

SENHA = "StrongPass123!"
CPF_A = "847.615.309-01"
CPF_B = "104.835.679-57"
CPF_C = "145.093.267-34"


def _payload_aluno(cpf=CPF_A, email="novo.aluno@buska.test", **extra):
    base = {"nome": "Aluno Novo", "email": email, "cpf": cpf, "password": SENHA}
    base.update(extra)
    return base


def _payload_motorista(cpf=CPF_B, email="novo.motorista@buska.test", cnh="12345678900", **extra):
    base = {
        "nome": "Motorista Novo",
        "email": email,
        "cpf": cpf,
        "password": SENHA,
        "cnh": cnh,
    }
    base.update(extra)
    return base


# ─── get_all_users ──────────────────────────────────────────────────────────


def test_get_all_users_lista_a_prefeitura_do_gestor(_db, gestor, aluno, motorista):
    resultado = get_all_users(str(gestor.user.id))

    ids = {u.id for u in resultado}
    assert {gestor.user.id, aluno.user.id, motorista.user.id} <= ids


def test_get_all_users_nao_vaza_outra_prefeitura(_db, gestor, other_aluno):
    assert other_aluno.user.id not in {u.id for u in get_all_users(str(gestor.user.id))}


def test_get_all_users_aluno_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        get_all_users(str(aluno.user.id))

    assert str(exc.value) == "Apenas gestores podem listar usuários"


def test_get_all_users_usuario_inexistente_404(_db):
    with pytest.raises(NotFoundError) as exc:
        get_all_users(str(uuid.uuid4()))

    assert str(exc.value) == "Usuário não encontrado"


def test_get_all_users_uuid_malformado_400_e_nao_500(_db):
    # Contraste com os outros serviços: aqui `_get_user_or_404` chama
    # `validate_uuid` antes de tocar o banco, então id torto vira 400 em vez
    # do 500 genérico que esse tipo de entrada provoca nos demais serviços.
    with pytest.raises(ValidationError):
        get_all_users("nao-e-uuid")


# ─── get_user_by_id ─────────────────────────────────────────────────────────


def test_get_user_by_id_sem_chamador_pula_a_autorizacao(_db, aluno):
    # `current_user_id=None` é o modo "uso interno": devolve qualquer usuário
    # sem checar nada.
    assert get_user_by_id(str(aluno.user.id)).id == aluno.user.id


def test_get_user_by_id_permite_ver_a_si_mesmo(_db, aluno):
    assert get_user_by_id(str(aluno.user.id), str(aluno.user.id)).id == aluno.user.id


def test_get_user_by_id_gestor_ve_usuario_da_propria_prefeitura(_db, gestor, aluno):
    assert get_user_by_id(str(aluno.user.id), str(gestor.user.id)).id == aluno.user.id


def test_get_user_by_id_gestor_de_outra_prefeitura_403(_db, other_gestor, aluno):
    with pytest.raises(ForbiddenError) as exc:
        get_user_by_id(str(aluno.user.id), str(other_gestor.user.id))

    assert str(exc.value) == "Sem permissão para visualizar este usuário"


def test_get_user_by_id_aluno_nao_ve_outro_aluno(_db, aluno, other_aluno):
    with pytest.raises(ForbiddenError):
        get_user_by_id(str(other_aluno.user.id), str(aluno.user.id))


def test_get_user_by_id_motorista_nao_ve_colega(_db, motorista, aluno):
    with pytest.raises(ForbiddenError):
        get_user_by_id(str(aluno.user.id), str(motorista.user.id))


def test_get_user_by_id_alvo_inexistente_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        get_user_by_id(str(uuid.uuid4()), str(gestor.user.id))

    assert str(exc.value) == "Usuário não encontrado"


# ─── update_user ────────────────────────────────────────────────────────────


def test_update_user_altera_nome_e_telefone_com_strip(_db, aluno):
    resultado = update_user(str(aluno.user.id), {"nome": "  Novo Nome  ", "telefone": " 999 "})

    assert resultado.nome == "Novo Nome"
    assert resultado.telefone == "999"


def test_update_user_troca_a_senha(_db, aluno):
    update_user(str(aluno.user.id), {"password": "OutraSenha123!"})

    _db.session.expire_all()
    assert check_password_hash(_db.session.get(User, aluno.user.id).senha_hash, "OutraSenha123!")


def test_update_user_email_duplicado_409(_db, aluno, other_aluno):
    with pytest.raises(ConflictError) as exc:
        update_user(str(aluno.user.id), {"email": other_aluno.user.email})

    assert str(exc.value) == "Email já está em uso"


def test_update_user_troca_para_email_livre(_db, aluno):
    resultado = update_user(str(aluno.user.id), {"email": "email.livre@buska.test"})

    assert resultado.email == "email.livre@buska.test"


def test_update_user_manter_o_proprio_email_nao_da_conflito(_db, aluno):
    resultado = update_user(str(aluno.user.id), {"email": aluno.user.email})

    assert resultado.email == aluno.user.email


def test_update_user_payload_vazio_nao_muda_nada(_db, aluno):
    nome_antes = aluno.user.nome

    assert update_user(str(aluno.user.id), {}).nome == nome_antes


def test_update_user_inexistente_404(_db):
    with pytest.raises(NotFoundError):
        update_user(str(uuid.uuid4()), {"nome": "X"})


def test_update_user_nao_tem_gate_de_autorizacao(_db, aluno, other_aluno):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    A função recebe o `user_id` alvo e não compara com nenhum chamador. Não há
    parâmetro de quem está pedindo, então qualquer rota que a exponha com um
    id vindo do corpo permite editar nome, e-mail e **senha** de outra conta.
    Hoje o controller passa o id do JWT, o que esconde a lacuna atrás da
    borda.
    """
    update_user(str(other_aluno.user.id), {"password": "InvadidaAgora123!"})

    _db.session.expire_all()
    alvo = _db.session.get(User, other_aluno.user.id)
    assert check_password_hash(alvo.senha_hash, "InvadidaAgora123!")


# ─── create_aluno_account ───────────────────────────────────────────────────


def test_create_aluno_gestor_cria_pendente(_db, gestor, prefeitura):
    novo = create_aluno_account(str(gestor.user.id), _payload_aluno())

    assert novo.role == UserRole.ALUNO
    assert novo.status == UserStatus.PENDING_SIGNUP
    assert novo.prefeitura_id == prefeitura.id
    assert novo.cpf == "84761530901"


def test_create_aluno_aluno_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        create_aluno_account(str(aluno.user.id), _payload_aluno())

    assert str(exc.value) == "Apenas gestores podem cadastrar alunos"


def test_create_aluno_email_duplicado_409(_db, gestor, aluno):
    with pytest.raises(ConflictError) as exc:
        create_aluno_account(str(gestor.user.id), _payload_aluno(email=aluno.user.email))

    assert str(exc.value) == "Email ou CPF já cadastrado"


def test_create_aluno_cpf_duplicado_409(_db, gestor):
    # Quando o registro existente foi criado pelo próprio `user_service`, o
    # CPF está gravado só com dígitos e a checagem encontra a duplicata.
    create_aluno_account(str(gestor.user.id), _payload_aluno())

    with pytest.raises(ConflictError) as exc:
        create_aluno_account(
            str(gestor.user.id), _payload_aluno(email="outro@buska.test", cpf=CPF_A)
        )

    assert str(exc.value) == "Email ou CPF já cadastrado"


def test_create_aluno_nao_detecta_cpf_duplicado_gravado_com_pontuacao(_db, gestor, aluno):
    """
    CARACTERIZAÇÃO DE FALHA CONHECIDA (não corrigida aqui).

    Os dois caminhos de cadastro gravam o CPF em formatos diferentes.
    `aluno_service.auto_cadastro` faz `cpf=data.get("cpf")` e guarda o valor
    cru, com pontos e traço. `user_service` faz `cpf=cpf_clean` e guarda só os
    dígitos. Os dois comparam contra `cpf_clean`.

    Resultado: um aluno que se cadastrou sozinho com "847.615.309-01" não é
    encontrado pela busca de "84761530901", e o gestor cria uma **segunda
    conta com o mesmo CPF**. O `aluno` do fixture reproduz o formato do
    auto-cadastro.
    """
    cpf_formatado = aluno.user.cpf
    assert "." in cpf_formatado, "o fixture precisa guardar o CPF formatado"

    novo = create_aluno_account(
        str(gestor.user.id), _payload_aluno(cpf=cpf_formatado, email="duplicado@buska.test")
    )

    assert novo.cpf == cpf_formatado.replace(".", "").replace("-", "")
    assert novo.id != aluno.user.id


def test_create_aluno_cpf_invalido_400(_db, gestor):
    with pytest.raises(ValidationError):
        create_aluno_account(str(gestor.user.id), _payload_aluno(cpf="111.111.111-11"))


def test_create_aluno_senha_fraca_400(_db, gestor):
    with pytest.raises(ValidationError):
        create_aluno_account(str(gestor.user.id), _payload_aluno(password="123"))


def test_create_aluno_telefone_vazio_vira_none(_db, gestor):
    novo = create_aluno_account(str(gestor.user.id), _payload_aluno(telefone="   "))

    assert novo.telefone is None


def test_create_aluno_checa_email_e_cpf_globalmente(_db, gestor, other_aluno):
    """
    CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui).

    A busca por e-mail e CPF não filtra por prefeitura. O gestor recebe 409 ao
    cadastrar alguém que já existe em **outra** prefeitura, o que vaza a
    existência do registro alheio, mesmo problema que a busca por placa de
    ônibus tem.
    """
    with pytest.raises(ConflictError):
        create_aluno_account(str(gestor.user.id), _payload_aluno(email=other_aluno.user.email))


# ─── create_motorista ───────────────────────────────────────────────────────


def test_create_motorista_gestor_cria(_db, gestor, prefeitura):
    novo = create_motorista(str(gestor.user.id), _payload_motorista())

    assert novo.role == UserRole.MOTORISTA
    assert novo.cnh == "12345678900"
    assert novo.prefeitura_id == prefeitura.id


def test_create_motorista_aluno_403(_db, aluno):
    with pytest.raises(ForbiddenError) as exc:
        create_motorista(str(aluno.user.id), _payload_motorista())

    assert str(exc.value) == "Apenas gestores podem cadastrar motoristas"


def test_create_motorista_sem_cnh_400(_db, gestor):
    with pytest.raises(ValidationError) as exc:
        create_motorista(str(gestor.user.id), _payload_motorista(cnh="   "))

    assert str(exc.value) == "CNH é obrigatória para motoristas"


def test_create_motorista_cnh_duplicada_409(_db, gestor, motorista):
    with pytest.raises(ConflictError) as exc:
        create_motorista(str(gestor.user.id), _payload_motorista(cnh=motorista.user.cnh, cpf=CPF_C))

    assert str(exc.value) == "CNH já cadastrada"


def test_create_motorista_email_duplicado_409(_db, gestor, aluno):
    with pytest.raises(ConflictError) as exc:
        create_motorista(str(gestor.user.id), _payload_motorista(email=aluno.user.email))

    assert str(exc.value) == "Email ou CPF já cadastrado"


def test_create_motorista_cnh_e_unica_entre_prefeituras(_db, gestor, other_motorista):
    """
    CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui).

    A busca de CNH não filtra por prefeitura. Pode ser proposital, porque CNH
    é única no país, mas o efeito é o mesmo que a busca por placa de ônibus
    tem: o 409 revela que a CNH
    existe em outra prefeitura. Registrado como pergunta em aberto.
    """
    with pytest.raises(ConflictError) as exc:
        create_motorista(
            str(gestor.user.id), _payload_motorista(cnh=other_motorista.user.cnh, cpf=CPF_C)
        )

    assert str(exc.value) == "CNH já cadastrada"


# ─── change_password ────────────────────────────────────────────────────────


def test_change_password_troca_a_senha(_db, aluno):
    change_password(
        str(aluno.user.id), {"current_password": SENHA, "new_password": "NovaSenha123!"}
    )

    _db.session.expire_all()
    assert check_password_hash(_db.session.get(User, aluno.user.id).senha_hash, "NovaSenha123!")


def test_change_password_senha_atual_errada_400(_db, aluno):
    with pytest.raises(ValidationError) as exc:
        change_password(
            str(aluno.user.id),
            {"current_password": "ErradaMesmo123!", "new_password": "NovaSenha123!"},
        )

    assert str(exc.value) == "A senha atual está incorreta"


def test_change_password_campos_faltando_400(_db, aluno):
    with pytest.raises(ValidationError) as exc:
        change_password(str(aluno.user.id), {"current_password": SENHA})

    assert str(exc.value) == "Senha atual e nova senha são obrigatórias"


def test_change_password_igual_a_atual_400(_db, aluno):
    with pytest.raises(ValidationError) as exc:
        change_password(str(aluno.user.id), {"current_password": SENHA, "new_password": SENHA})

    assert str(exc.value) == "Nova senha deve ser diferente da senha atual"


def test_change_password_nova_senha_fraca_400(_db, aluno):
    with pytest.raises(ValidationError):
        change_password(str(aluno.user.id), {"current_password": SENHA, "new_password": "123"})


def test_change_password_compara_antes_de_conferir_a_senha_atual(_db, aluno):
    """
    CARACTERIZAÇÃO DE DIVERGÊNCIA (não corrigida aqui).

    A checagem "nova igual à atual" roda **antes** da verificação da senha
    atual. Mandando o mesmo valor nos dois campos, quem não conhece a senha
    recebe 400 "deve ser diferente" em vez de 401. A resposta confirma apenas
    que os dois campos eram iguais, não que o valor estava certo, então não é
    oráculo de senha. Fica registrado porque a ordem parece acidental.
    """
    with pytest.raises(ValidationError) as exc:
        change_password(
            str(aluno.user.id),
            {"current_password": "ChutePorAcaso1!", "new_password": "ChutePorAcaso1!"},
        )

    assert str(exc.value) == "Nova senha deve ser diferente da senha atual"


# ─── get_motoristas_by_municipio ────────────────────────────────────────────


def test_get_motoristas_lista_os_da_prefeitura(_db, gestor, motorista, aluno):
    resultado = get_motoristas_by_municipio(str(gestor.user.id))

    assert [m.id for m in resultado] == [motorista.user.id]


def test_get_motoristas_nao_vaza_outra_prefeitura(_db, gestor, other_motorista):
    assert other_motorista.user.id not in {
        m.id for m in get_motoristas_by_municipio(str(gestor.user.id))
    }


def test_get_motoristas_nao_exige_papel_de_gestor(_db, aluno, motorista):
    # Usa `_get_user_or_404`, não `_get_gestor_or_403`: qualquer usuário lista
    # os motoristas da própria prefeitura.
    assert [m.id for m in get_motoristas_by_municipio(str(aluno.user.id))] == [motorista.user.id]


# ─── update_profile ─────────────────────────────────────────────────────────


def test_update_profile_altera_nome_telefone_e_preferencia(_db, aluno):
    resultado = update_profile(
        str(aluno.user.id),
        {"nome": " Fulano ", "telefone": " 88 ", "receber_notificacoes": False},
    )

    assert resultado.nome == "Fulano"
    assert resultado.telefone == "88"
    assert resultado.receber_notificacoes is False


def test_update_profile_motorista_altera_cnh(_db, motorista):
    resultado = update_profile(str(motorista.user.id), {"cnh": " 99887766554 "})

    assert resultado.cnh == "99887766554"


def test_update_profile_cnh_duplicada_409(_db, gestor, motorista, other_motorista):
    with pytest.raises(ConflictError) as exc:
        update_profile(str(motorista.user.id), {"cnh": other_motorista.user.cnh})

    assert str(exc.value) == "CNH já cadastrada para outro motorista"


def test_update_profile_motorista_mantendo_a_propria_cnh_passa(_db, motorista):
    resultado = update_profile(str(motorista.user.id), {"cnh": motorista.user.cnh})

    assert resultado.cnh == motorista.user.cnh


def test_update_profile_cnh_e_ignorada_para_aluno(_db, aluno):
    # O ramo da CNH só roda para MOTORISTA, então o campo é descartado em
    # silêncio em vez de virar erro.
    update_profile(str(aluno.user.id), {"cnh": "12345678900"})

    assert not hasattr(_db.session.get(User, aluno.user.id), "cnh")


def test_update_profile_receber_notificacoes_aceita_valor_truthy(_db, aluno):
    # `bool(data[...])` converte qualquer coisa, então "não" vira True.
    resultado = update_profile(str(aluno.user.id), {"receber_notificacoes": "nao"})

    assert resultado.receber_notificacoes is True


# ─── delete_motorista ───────────────────────────────────────────────────────


def test_delete_motorista_gestor_remove(_db, gestor, motorista):
    delete_motorista(str(gestor.user.id), str(motorista.user.id))

    assert _db.session.get(User, motorista.user.id) is None


def test_delete_motorista_aluno_403(_db, aluno, motorista):
    with pytest.raises(ForbiddenError) as exc:
        delete_motorista(str(aluno.user.id), str(motorista.user.id))

    assert str(exc.value) == "Apenas gestores podem remover motoristas"


def test_delete_motorista_inexistente_404(_db, gestor):
    with pytest.raises(NotFoundError) as exc:
        delete_motorista(str(gestor.user.id), str(uuid.uuid4()))

    assert str(exc.value) == "Motorista não encontrado"


def test_delete_motorista_alvo_que_nao_e_motorista_404(_db, gestor, aluno):
    # Papel errado recebe 404 em vez de 400, escondendo a existência do id.
    with pytest.raises(NotFoundError) as exc:
        delete_motorista(str(gestor.user.id), str(aluno.user.id))

    assert str(exc.value) == "Motorista não encontrado"


def test_delete_motorista_de_outra_prefeitura_403(_db, gestor, other_motorista):
    with pytest.raises(ForbiddenError) as exc:
        delete_motorista(str(gestor.user.id), str(other_motorista.user.id))

    assert str(exc.value) == "Proibido remover motoristas de outra prefeitura"
    assert _db.session.get(User, other_motorista.user.id) is not None


def test_delete_motorista_com_viagem_vinculada_400(_db, gestor, motorista, horario_rota):
    from datetime import date, timedelta

    from app.models.enum import StatusViagem
    from app.models.viagem import Viagem

    viagem = Viagem(
        data=date.today() + timedelta(days=1),
        horario_rota_id=horario_rota.id,
        status=StatusViagem.AGENDADA,
        motorista_id=motorista.user.id,
    )
    _db.session.add(viagem)
    _db.session.commit()

    with pytest.raises(AppError) as exc:
        delete_motorista(str(gestor.user.id), str(motorista.user.id))

    assert str(exc.value) == (
        "Não é possível remover este motorista pois ele possui viagens vinculadas"
    )
    assert exc.value.status_code == 400


def test_delete_motorista_erro_generico_nao_vira_mensagem_de_viagem_vinculada(
    _db, gestor, motorista, monkeypatch
):
    """Corrigido: só o `ConflictError` do `transactional()`, que vem de
    `IntegrityError`, recebe o rótulo de viagem vinculada. Uma queda de conexão
    sobe crua. Era o mesmo defeito do `:127` do `pontos_service`.

    O caso legítimo segue fixado em `test_delete_motorista_com_viagem_vinculada_400`.
    """

    def falha_generica():
        raise RuntimeError("conexão perdida")

    monkeypatch.setattr(user_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        delete_motorista(str(gestor.user.id), str(motorista.user.id))


# ─── update_fcm_token ───────────────────────────────────────────────────────


def test_update_fcm_token_grava(_db, aluno):
    update_fcm_token(str(aluno.user.id), {"fcm_token": "token-novo"})

    _db.session.expire_all()
    assert _db.session.get(User, aluno.user.id).fcm_token == "token-novo"


def test_update_fcm_token_sem_o_campo_apaga_o_token(_db, aluno):
    # `data.get("fcm_token")` devolve None, então um payload vazio desliga o
    # push em vez de ser rejeitado.
    aluno.user.fcm_token = "token-antigo"
    _db.session.commit()

    update_fcm_token(str(aluno.user.id), {})

    _db.session.expire_all()
    assert _db.session.get(User, aluno.user.id).fcm_token is None


def test_update_fcm_token_usuario_inexistente_404(_db):
    with pytest.raises(NotFoundError):
        update_fcm_token(str(uuid.uuid4()), {"fcm_token": "x"})


# ─── helper morto ───────────────────────────────────────────────────────────
# `_require_active` foi removido. Estava definido e nunca era chamado,
# dentro ou fora do módulo. Os três testes que o fixavam saíram junto.


def test_motorista_do_fixture_tem_cnh(_db, motorista):
    # Guarda de sanidade: vários testes acima dependem de `motorista.user.cnh`.
    assert isinstance(motorista.user, Motorista)
    assert motorista.user.cnh


# ─── vazamento de str(e) nos blocos genéricos ───────────────────────────────


@pytest.mark.parametrize(
    "nome_do_caso",
    [
        "update_user",
        "create_aluno_account",
        "create_motorista",
        "change_password",
        "update_profile",
    ],
)
def test_erro_no_commit_nao_vaza_texto_do_driver(_db, gestor, aluno, monkeypatch, nome_do_caso):
    """Corrigido: as cinco funções embrulhavam a exceção num `AppError`
    500 interpolando `str(e)`, entregando SQL e nome de coluna ao cliente. Agora
    a exceção sobe intacta e o handler genérico responde 500 "Erro interno do
    servidor"."""
    chamadas = {
        "update_user": lambda: update_user(str(aluno.user.id), {"nome": "Novo"}),
        "create_aluno_account": lambda: create_aluno_account(str(gestor.user.id), _payload_aluno()),
        "create_motorista": lambda: create_motorista(str(gestor.user.id), _payload_motorista()),
        "change_password": lambda: change_password(
            str(aluno.user.id), {"current_password": SENHA, "new_password": "NovaSenha123!"}
        ),
        "update_profile": lambda: update_profile(str(aluno.user.id), {"nome": "Novo"}),
    }

    def falha_generica():
        raise RuntimeError("boom do driver")

    monkeypatch.setattr(user_service.db.session, "commit", falha_generica)

    with pytest.raises(RuntimeError):
        chamadas[nome_do_caso]()


@pytest.mark.parametrize(
    "nome_do_caso", ["update_user", "create_aluno_account", "create_motorista"]
)
def test_erro_de_dominio_no_commit_passa_sem_ser_embrulhado(
    _db, gestor, aluno, monkeypatch, nome_do_caso
):
    """
    CARACTERIZAÇÃO DE CÓDIGO MORTO (não removido aqui).

    As três funções têm um `except (ValidationError, ConflictError, ...)` que
    repassa o erro antes do `except Exception`. Na prática ele nunca dispara:
    o `try` só envolve o `commit`, e todas as validações rodam **antes** dele.
    Só um commit que levantasse erro de domínio alcançaria o ramo, o que não
    acontece.

    Este teste força o cenário para provar que a cláusula funciona, e para
    registrar que ela é defensiva sem ter o que defender.
    """
    chamadas = {
        "update_user": lambda: update_user(str(aluno.user.id), {"nome": "Novo"}),
        "create_aluno_account": lambda: create_aluno_account(str(gestor.user.id), _payload_aluno()),
        "create_motorista": lambda: create_motorista(str(gestor.user.id), _payload_motorista()),
    }

    def conflito_no_commit():
        raise ConflictError("conflito vindo do commit")

    monkeypatch.setattr(user_service.db.session, "commit", conflito_no_commit)

    with pytest.raises(ConflictError) as exc:
        chamadas[nome_do_caso]()

    assert exc.value.status_code == 409
    assert str(exc.value) == "conflito vindo do commit"
