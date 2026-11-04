"""
Characterization tests for ``app/services/aluno_service.py``.

Purpose: pin the CURRENT observable behaviour of every public function in the
module so the upcoming refactor can be proven behaviour-preserving. These are
deliberately NOT "should" tests — where the behaviour pinned here is a known
bug, the test name and comment say so. When that behaviour is fixed, the
corresponding test must be updated in the SAME PR that changes it.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.enum import TipoInstituicao, UserStatus
from app.models.geo import Endereco, Instituicao, Ponto
from app.models.rota import RotaPonto
from app.models.user import Aluno
from app.services.aluno_service import (
    aprovar_aluno,
    auto_cadastro,
    delete_me,
    get_aluno_by_id,
    get_guardian_consent_info,
    list_alunos_gestor,
    record_guardian_consent,
    update_me,
)

pytestmark = pytest.mark.integration


# ─── helpers ───────────────────────────────────────────────────────────────────


def make_cpf(base: str = "529982247") -> str:
    """Build a checksum-valid CPF from a 9-digit base (digits only)."""

    def digit(partial: str, weight_start: int) -> int:
        total = sum(int(partial[i]) * (weight_start - i) for i in range(len(partial)))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    d1 = digit(base, 10)
    d2 = digit(f"{base}{d1}", 11)
    return f"{base}{d1}{d2}"


ENDERECO = {
    "latitude": -7.23,
    "longitude": -35.88,
    "logradouro": "Rua Teste",
    "numero": "100",
    "bairro": "Centro",
    "cidade": "Campina Grande",
    "cep": "58400000",
}


def signup_payload(**overrides):
    data = {
        "nome": "Fulano de Tal",
        "email": "fulano@buska.test",
        "password": "SenhaForte123",
        "cpf": make_cpf(),
        "telefone": "83999990000",
        "matricula": "2024001",
        "endereco_casa": dict(ENDERECO),
        "data_nascimento": date.today() - timedelta(days=365 * 25),
    }
    data.update(overrides)
    return data


@pytest.fixture()
def aluno_ativo(_db, aluno):
    """The ``aluno`` fixture inherits the model default (PENDING_SIGNUP), which
    makes ``update_me`` run the signup-completion branch. Tests that target the
    plain-update path need an already-ACTIVE aluno."""
    aluno.user.status = UserStatus.ACTIVE
    _db.session.commit()
    return aluno


@pytest.fixture()
def instituicao(_db, prefeitura):
    inst = Instituicao(
        fonte="MANUAL",
        codigo_externo="INST-CHAR-1",
        nome="Escola Municipal de Teste",
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        uf="PB",
        prefeitura_id=prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


# ─── auto_cadastro ─────────────────────────────────────────────────────────────


def test_auto_cadastro_adulto_cria_aluno_ponto_e_endereco(_db, instituicao, prefeitura):
    aluno = auto_cadastro(signup_payload(instituicao_id=str(instituicao.id)))

    assert aluno.status == UserStatus.PENDING_SIGNUP
    assert str(aluno.prefeitura_id) == str(prefeitura.id)  # inferred from instituicao
    assert str(aluno.instituicao_id) == str(instituicao.id)
    assert aluno.guardian_token is None
    assert aluno.senha_hash and aluno.senha_hash != "SenhaForte123"

    ponto = _db.session.get(Ponto, aluno.ponto_casa_id)
    assert ponto is not None
    assert ponto.apelido == "Casa: Fulano de Tal"
    endereco = Endereco.query.filter_by(ponto_id=aluno.ponto_casa_id).first()
    assert endereco is not None
    assert endereco.cidade == "Campina Grande"


def test_auto_cadastro_persiste_cpf_e_email_crus(_db, instituicao):
    """CHARACTERIZATION OF A BUG (not fixed here).

    ``validate_cpf``/``validate_email`` return normalized values, but the Aluno
    row is built from ``data.get("cpf")`` / ``data.get("email")`` — the RAW
    input. So a formatted CPF is stored formatted, while the duplicate check
    queries the digits-only form: the app-level guard never matches and the
    collision is only caught by the DB UNIQUE constraint, surfacing as a
    generic 500 instead of the intended ConflictError 409.
    """
    cpf = make_cpf()
    formatted = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"

    aluno = auto_cadastro(
        signup_payload(instituicao_id=str(instituicao.id), cpf=formatted, email="A@Buska.TEST")
    )

    assert aluno.cpf == formatted  # stored raw, NOT digits-only
    assert aluno.email == "A@Buska.TEST"  # stored raw, NOT lowercased

    # Same CPF again: o guard de aplicação continua errando o alvo, porque
    # compara contra a forma só com dígitos. A colisão segue sendo pega apenas
    # pela UNIQUE do banco. O que mudou no R7i é o status: o `transactional()`
    # mapeia `IntegrityError` para `ConflictError` 409, que é o código que a
    # função pretendia devolver desde sempre.
    #
    # A causa raiz continua aberta no B49: `auto_cadastro` grava o CPF cru e o
    # `user_service` grava só os dígitos, então as duas rotas de cadastro
    # divergem e a mensagem 409 é genérica em vez de nomear o campo.
    with pytest.raises(ConflictError) as exc:
        auto_cadastro(
            signup_payload(
                instituicao_id=str(instituicao.id), cpf=formatted, email="outro@buska.test"
            )
        )
    assert exc.value.status_code == 409
    assert str(exc.value) == "Violação de integridade"


def test_auto_cadastro_instituicao_inexistente(_db):
    import uuid

    with pytest.raises(NotFoundError) as exc:
        auto_cadastro(signup_payload(instituicao_id=str(uuid.uuid4())))
    assert "Instituição não encontrada" in exc.value.message


def test_auto_cadastro_email_duplicado(_db, instituicao, aluno):
    with pytest.raises(ConflictError) as exc:
        auto_cadastro(signup_payload(instituicao_id=str(instituicao.id), email=aluno.user.email))
    assert exc.value.field == "email"
    assert exc.value.status_code == 409


def test_auto_cadastro_cpf_duplicado(_db, instituicao):
    cpf = make_cpf()
    auto_cadastro(signup_payload(instituicao_id=str(instituicao.id), cpf=cpf))

    with pytest.raises(ConflictError) as exc:
        auto_cadastro(
            signup_payload(instituicao_id=str(instituicao.id), cpf=cpf, email="outro@buska.test")
        )
    assert exc.value.field == "cpf"


def test_auto_cadastro_sem_endereco_propaga_validation_error(_db, instituicao):
    """AppError subclasses are re-raised as-is (the ``except AppError`` arm)."""
    with pytest.raises(ValidationError) as exc:
        auto_cadastro(signup_payload(instituicao_id=str(instituicao.id), endereco_casa=None))
    assert exc.value.status_code == 400
    assert exc.value.details == {"field": "endereco_casa"}


def test_auto_cadastro_senha_fraca_propaga_validation_error(_db, instituicao):
    with pytest.raises(ValidationError):
        auto_cadastro(signup_payload(instituicao_id=str(instituicao.id), password="123"))


def test_auto_cadastro_menor_sem_email_responsavel(_db, instituicao):
    with pytest.raises(ValidationError) as exc:
        auto_cadastro(
            signup_payload(
                instituicao_id=str(instituicao.id),
                data_nascimento=date.today() - timedelta(days=365 * 15),
            )
        )
    assert exc.value.details == {"field": "email_responsavel"}

    # rollback happened: nothing was persisted
    assert _db.session.query(Aluno).filter_by(email="fulano@buska.test").first() is None


def test_auto_cadastro_menor_gera_token_e_envia_email(_db, instituicao):
    with patch("app.services.aluno_service.send_email") as mock_send:
        aluno = auto_cadastro(
            signup_payload(
                instituicao_id=str(instituicao.id),
                data_nascimento=date.today() - timedelta(days=365 * 15),
                email_responsavel="  Mae@Buska.TEST  ",
            )
        )

    assert aluno.is_minor is True
    assert aluno.status == UserStatus.PENDING_SIGNUP  # stays until consent
    assert aluno.guardian_token  # single-use token generated
    assert aluno.email_responsavel == "mae@buska.test"  # stripped + lowercased
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["to"] == "mae@buska.test"
    assert aluno.guardian_token in mock_send.call_args.kwargs["body_html"]


def test_auto_cadastro_menor_email_falhando_nao_quebra_cadastro(_db, instituicao):
    """``_send_guardian_consent_email`` swallows any sender exception."""
    with patch("app.services.aluno_service.send_email", side_effect=RuntimeError("smtp down")):
        aluno = auto_cadastro(
            signup_payload(
                instituicao_id=str(instituicao.id),
                data_nascimento=date.today() - timedelta(days=365 * 15),
                email_responsavel="mae@buska.test",
            )
        )

    assert aluno.id is not None
    assert _db.session.get(Aluno, aluno.id) is not None


# ─── guardian consent ──────────────────────────────────────────────────────────


@pytest.fixture()
def aluno_menor(_db, instituicao):
    with patch("app.services.aluno_service.send_email"):
        return auto_cadastro(
            signup_payload(
                instituicao_id=str(instituicao.id),
                data_nascimento=date.today() - timedelta(days=365 * 15),
                email_responsavel="mae@buska.test",
            )
        )


def test_get_guardian_consent_info_ok(aluno_menor):
    found = get_guardian_consent_info(aluno_menor.guardian_token)
    assert found.id == aluno_menor.id


def test_get_guardian_consent_info_token_invalido(_db):
    with pytest.raises(NotFoundError) as exc:
        get_guardian_consent_info("nao-existe")
    assert "inválido ou já utilizado" in exc.value.message


def test_record_guardian_consent_avanca_para_pending_approval(_db, aluno_menor, gestor):
    token = aluno_menor.guardian_token

    aluno = record_guardian_consent(token)

    assert aluno.status == UserStatus.PENDING_APPROVAL
    assert aluno.guardian_consented_at is not None
    assert aluno.guardian_token is None  # single-use: token is burned

    from app.models.notificacao import Notificacao

    notifs = _db.session.query(Notificacao).filter_by(usuario_id=str(gestor.user.id)).all()
    assert len(notifs) == 1
    assert notifs[0].titulo == "Novo cadastro aguardando aprovação"


def test_record_guardian_consent_token_reutilizado(_db, aluno_menor, gestor):
    token = aluno_menor.guardian_token
    record_guardian_consent(token)

    with pytest.raises(NotFoundError):
        record_guardian_consent(token)


def test_record_guardian_consent_ja_consentido(_db, aluno_menor):
    aluno_menor.guardian_consented_at = datetime.now(UTC)
    _db.session.commit()

    with pytest.raises(ValidationError) as exc:
        record_guardian_consent(aluno_menor.guardian_token)
    assert "já registrado anteriormente" in exc.value.message


def test_record_guardian_consent_link_expirado(_db, aluno_menor):
    aluno_menor.created_at = datetime.now(UTC) - timedelta(days=8)
    _db.session.commit()

    with pytest.raises(ValidationError) as exc:
        record_guardian_consent(aluno_menor.guardian_token)
    assert "expirou" in exc.value.message

    _db.session.refresh(aluno_menor)
    assert aluno_menor.status == UserStatus.PENDING_SIGNUP


# ─── update_me ─────────────────────────────────────────────────────────────────


def test_update_me_aluno_inexistente(_db):
    import uuid

    with pytest.raises(NotFoundError):
        update_me(str(uuid.uuid4()), {"nome": "X"})


def test_update_me_atualiza_campos_simples(_db, aluno_ativo):
    atualizado = update_me(
        str(aluno_ativo.user.id),
        {"nome": "Novo Nome", "telefone": "83988887777", "matricula": "999"},
    )

    assert atualizado.nome == "Novo Nome"
    assert atualizado.telefone == "83988887777"
    assert atualizado.matricula == "999"


def test_update_me_troca_para_instituicao_cadastrada_da_prefeitura(_db, aluno_ativo, instituicao):
    atualizado = update_me(str(aluno_ativo.user.id), {"instituicao_id": instituicao.id})

    assert atualizado.instituicao_id == instituicao.id


def test_update_me_recusa_instituicao_de_outra_prefeitura(_db, aluno_ativo, other_prefeitura):
    de_fora = Instituicao(
        fonte="MANUAL",
        codigo_externo="INST-FORA",
        nome="Escola de Outra Prefeitura",
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        uf="PB",
        prefeitura_id=other_prefeitura.id,
    )
    _db.session.add(de_fora)
    _db.session.commit()

    with pytest.raises(ValidationError):
        update_me(str(aluno_ativo.user.id), {"instituicao_id": de_fora.id})

    assert aluno_ativo.user.instituicao_id != de_fora.id


def test_update_me_recusa_instituicao_que_nao_existe(_db, aluno_ativo):
    import uuid

    with pytest.raises(ValidationError):
        update_me(str(aluno_ativo.user.id), {"instituicao_id": uuid.uuid4()})


def test_update_me_ignora_campos_nao_listados(_db, aluno_ativo):
    """Only the 5 whitelisted fields are copied; ``email`` is silently ignored."""
    original = aluno_ativo.user.email
    atualizado = update_me(str(aluno_ativo.user.id), {"email": "hacker@buska.test"})
    assert atualizado.email == original


def test_update_me_cria_ponto_e_endereco_quando_nao_existe(_db, aluno_ativo):
    aluno_ativo.user.ponto_casa_id = None
    _db.session.commit()

    atualizado = update_me(str(aluno_ativo.user.id), {"endereco_casa": dict(ENDERECO)})

    assert atualizado.ponto_casa_id is not None
    ponto = _db.session.get(Ponto, atualizado.ponto_casa_id)
    assert float(ponto.latitude) == pytest.approx(-7.23)
    assert ponto.apelido == f"Casa: {atualizado.nome}"
    assert Endereco.query.filter_by(ponto_id=atualizado.ponto_casa_id).first() is not None


def test_update_me_atualiza_endereco_existente(_db, aluno_ativo):
    update_me(str(aluno_ativo.user.id), {"endereco_casa": dict(ENDERECO)})
    ponto_id = aluno_ativo.user.ponto_casa_id

    novo = dict(ENDERECO, logradouro="Rua Nova", latitude=-8.0)
    atualizado = update_me(str(aluno_ativo.user.id), {"nome": "Zé", "endereco_casa": novo})

    assert atualizado.ponto_casa_id == ponto_id  # reused, not recreated
    endereco = Endereco.query.filter_by(ponto_id=ponto_id).first()
    assert endereco.logradouro == "Rua Nova"
    ponto = _db.session.get(Ponto, ponto_id)
    assert float(ponto.latitude) == pytest.approx(-8.0)
    assert ponto.apelido == "Casa: Zé"  # apelido follows "nome" when both are sent


def test_update_me_completa_signup_do_adulto(_db, aluno_pending, instituicao):
    aluno_pending.user.instituicao_id = instituicao.id
    aluno_pending.user.matricula = "2024999"
    _db.session.commit()

    atualizado = update_me(str(aluno_pending.user.id), {"endereco_casa": dict(ENDERECO)})

    assert atualizado.status == UserStatus.ACTIVE
    assert atualizado.signup_completed_at is not None


def test_update_me_completa_signup_sem_matricula(_db, aluno_pending, instituicao):
    aluno_pending.user.instituicao_id = instituicao.id
    aluno_pending.user.matricula = None
    _db.session.commit()

    atualizado = update_me(str(aluno_pending.user.id), {"endereco_casa": dict(ENDERECO)})

    assert atualizado.status == UserStatus.ACTIVE


def test_update_me_pendencias_retorna_400(_db, aluno_pending):
    """

    ``update_me`` raises ValidationError(400) for an incomplete signup. The bare
    ``except Exception`` used to swallow it and re-raise AppError 500, turning a
    client input problem into a server error.
    """
    aluno_pending.user.matricula = None
    aluno_pending.user.instituicao_id = None
    _db.session.commit()

    with pytest.raises(ValidationError) as exc:
        update_me(str(aluno_pending.user.id), {"nome": "Sem Dados"})

    assert exc.value.status_code == 400
    assert "Cadastro precisa ser finalizado" in exc.value.message
    assert exc.value.details["missing"] == [
        "instituicao_id",
        "endereco_casa.latitude/longitude",
    ]


def test_update_me_persiste_instituicao_id_e_completa_cadastro(_db, aluno_pending, instituicao):
    aluno_pending.user.matricula = "123"
    aluno_pending.user.instituicao_id = None
    _db.session.commit()

    atualizado = update_me(
        str(aluno_pending.user.id),
        {"instituicao_id": instituicao.id, "endereco_casa": dict(ENDERECO)},
    )

    assert atualizado.status == UserStatus.ACTIVE
    assert atualizado.instituicao_id == instituicao.id


def test_update_me_menor_pendente_nao_completa_signup(_db, aluno_menor):
    """The completion block is guarded by ``not aluno.is_minor``: a minor stays
    PENDING_SIGNUP no matter how complete the payload is."""
    atualizado = update_me(str(aluno_menor.id), {"nome": "Menor", "endereco_casa": dict(ENDERECO)})
    assert atualizado.status == UserStatus.PENDING_SIGNUP


# ─── delete_me ─────────────────────────────────────────────────────────────────


def test_delete_me_sem_ponto_casa(_db, aluno_ativo):
    """The only path that currently works: aluno without a home point."""
    aluno_ativo.user.ponto_casa_id = None
    _db.session.commit()
    aluno_id = aluno_ativo.user.id

    delete_me(str(aluno_id))

    assert _db.session.get(Aluno, aluno_id) is None


def test_delete_me_com_ponto_casa(_db, instituicao):
    """

    ``delete_me`` used to delete ``aluno.ponto_casa`` while
    ``aluno.ponto_casa_id`` still referenced it. The cascade-resolution query
    autoflushed the pending Ponto delete before the Aluno row was removed, so
    Postgres rejected it with ``aluno_ponto_casa_id_fkey`` and the caller got a
    generic 500, with the account still in place.

    Since ``auto_cadastro`` ALWAYS creates a ponto_casa, self-service account
    deletion was broken for every student who signed up through the app.
    """
    aluno = auto_cadastro(signup_payload(instituicao_id=str(instituicao.id)))
    aluno_id, ponto_id = aluno.id, aluno.ponto_casa_id
    assert ponto_id is not None

    delete_me(str(aluno_id))

    assert _db.session.get(Aluno, aluno_id) is None
    # o ponto de casa (e o endereço pendurado nele) saem junto
    assert _db.session.get(Ponto, ponto_id) is None
    assert Endereco.query.filter_by(ponto_id=ponto_id).first() is None


def test_delete_me_mantem_ponto_casa_usado_por_rota(_db, instituicao, rota):
    """O ponto de casa pode ter virado parada de uma rota (rota_ponto tem FK
    RESTRICT). A conta ainda assim precisa ser excluída — só o ponto fica."""
    aluno = auto_cadastro(signup_payload(instituicao_id=str(instituicao.id)))
    aluno_id, ponto_id = aluno.id, aluno.ponto_casa_id

    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=ponto_id, ordem=1))
    _db.session.commit()

    delete_me(str(aluno_id))

    assert _db.session.get(Aluno, aluno_id) is None
    assert _db.session.get(Ponto, ponto_id) is not None


def test_delete_me_aluno_inexistente(_db):
    import uuid

    with pytest.raises(NotFoundError) as exc:
        delete_me(str(uuid.uuid4()))
    assert "Aluno não encontrado" in exc.value.message


# ─── get_aluno_by_id ───────────────────────────────────────────────────────────


def test_get_aluno_by_id_ok(_db, gestor, aluno):
    found = get_aluno_by_id(str(gestor.user.id), str(aluno.user.id))
    assert found.id == aluno.user.id


def test_get_aluno_by_id_exige_gestor(_db, aluno, other_aluno):
    with pytest.raises(ForbiddenError) as exc:
        get_aluno_by_id(str(aluno.user.id), str(other_aluno.user.id))
    assert "Apenas gestores" in exc.value.message


def test_get_aluno_by_id_inexistente(_db, gestor):
    import uuid

    with pytest.raises(NotFoundError):
        get_aluno_by_id(str(gestor.user.id), str(uuid.uuid4()))


def test_get_aluno_by_id_bloqueia_cross_tenant(_db, gestor, other_aluno):
    with pytest.raises(ForbiddenError) as exc:
        get_aluno_by_id(str(gestor.user.id), str(other_aluno.user.id))
    assert "não pertence à sua prefeitura" in exc.value.message


# ─── list_alunos_gestor ────────────────────────────────────────────────────────


def test_list_alunos_gestor_escopo_por_prefeitura(_db, gestor, aluno, other_aluno):
    ids = {a.id for a in list_alunos_gestor(str(gestor.user.id))}
    assert aluno.user.id in ids
    assert other_aluno.user.id not in ids


def test_list_alunos_gestor_exige_gestor(_db, aluno):
    with pytest.raises(ForbiddenError):
        list_alunos_gestor(str(aluno.user.id))


def test_list_alunos_gestor_filtro_status_valido(_db, gestor, aluno_ativo, aluno_pending):
    pendentes = list_alunos_gestor(str(gestor.user.id), status="PENDING_SIGNUP")
    assert [a.id for a in pendentes] == [aluno_pending.user.id]


def test_list_alunos_gestor_status_invalido_levanta_erro(_db, gestor, aluno, aluno_pending):
    """Corrigido pelo PR #42: um status desconhecido agora levanta
    ``ValidationError`` em vez de ser engolido e a listagem cair pra sem
    filtro."""
    with pytest.raises(ValidationError):
        list_alunos_gestor(str(gestor.user.id), status="NAO_EXISTE")


# ─── aprovar_aluno ─────────────────────────────────────────────────────────────


def test_aprovar_aluno_ativa_e_notifica(_db, gestor, aluno_pending):
    aluno_pending.user.status = UserStatus.PENDING_APPROVAL
    _db.session.commit()

    aprovado = aprovar_aluno(str(gestor.user.id), str(aluno_pending.user.id))

    assert aprovado.status == UserStatus.ACTIVE
    assert aprovado.signup_completed_at is not None

    from app.models.notificacao import Notificacao

    notifs = _db.session.query(Notificacao).filter_by(usuario_id=str(aluno_pending.user.id)).all()
    assert len(notifs) == 1
    assert notifs[0].titulo == "Cadastro Aprovado!"


def test_aprovar_aluno_exige_gestor(_db, aluno, aluno_pending):
    with pytest.raises(ForbiddenError) as exc:
        aprovar_aluno(str(aluno.user.id), str(aluno_pending.user.id))
    assert "Apenas gestores" in exc.value.message


def test_aprovar_aluno_inexistente(_db, gestor):
    import uuid

    with pytest.raises(NotFoundError):
        aprovar_aluno(str(gestor.user.id), str(uuid.uuid4()))


def test_aprovar_aluno_bloqueia_cross_tenant(_db, gestor, other_aluno):
    other_aluno.user.status = UserStatus.PENDING_APPROVAL
    _db.session.commit()

    with pytest.raises(ForbiddenError):
        aprovar_aluno(str(gestor.user.id), str(other_aluno.user.id))


def test_aprovar_aluno_status_errado(_db, gestor, aluno_ativo):
    """Approving an ACTIVE aluno is a 400 — only PENDING_APPROVAL is allowed."""
    with pytest.raises(ValidationError) as exc:
        aprovar_aluno(str(gestor.user.id), str(aluno_ativo.user.id))
    assert "não está aguardando aprovação" in exc.value.message
