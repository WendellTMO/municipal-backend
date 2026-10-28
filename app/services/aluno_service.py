"""Student (Aluno) service - registration, profile management."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.core.authz import get_gestor_or_403
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import UserRole, UserStatus
from app.models.geo import Endereco, Instituicao, Ponto
from app.models.user import Aluno, Gestor, User
from app.services.notificacao_service import NotificacaoService
from app.utils import audit_logger, validate_cpf, validate_email, validate_password
from app.utils.email_sender import send_email

logger = logging.getLogger(__name__)


# ─── Guardian email ────────────────────────────────────────────────────────────


def enviar_email_consentimento_responsavel(aluno: Aluno) -> None:
    """Send a consent request email to the aluno's guardian."""
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:8081")
    link = f"{frontend_url.rstrip('/')}/guardian-consent?token={aluno.guardian_token}"

    subject = "Autorização necessária — BusKa"
    body_plain = (
        f"Olá!\n\n"
        f"O(A) estudante {aluno.nome} solicitou cadastro no BusKa, "
        f"aplicativo de transporte escolar.\n\n"
        f"Como responsável legal, você precisa autorizar o uso do app antes que o cadastro "
        f"seja enviado para análise do gestor municipal.\n\n"
        f"Clique no link abaixo para confirmar ou recusar:\n{link}\n\n"
        f"Este link é válido por 7 dias.\n\n"
        f"Atenciosamente,\nEquipe BusKa"
    )
    body_html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
      <h2 style="color:#0347D0">Autorização de Cadastro — BusKa</h2>
      <p>Olá!</p>
      <p>O(A) estudante <strong>{aluno.nome}</strong> solicitou cadastro no BusKa,
         aplicativo de transporte escolar municipal.</p>
      <p>Como responsável legal, sua autorização é necessária para que o cadastro
         seja encaminhado ao gestor municipal.</p>
      <a href="{link}"
         style="display:inline-block;margin:16px 0;padding:14px 28px;
                background:#0347D0;color:#fff;border-radius:8px;
                text-decoration:none;font-weight:600">
        Clique aqui para responder
      </a>
      <p style="color:#666;font-size:13px">
        Se o botão não funcionar, copie e cole este link no seu navegador:<br>
        <a href="{link}">{link}</a>
      </p>
      <p style="color:#666;font-size:13px">Este link expira em 7 dias.</p>
    </div>
    """
    try:
        send_email(
            to=aluno.email_responsavel,
            subject=subject,
            body_plain=body_plain,
            body_html=body_html,
        )
    except Exception:
        logger.exception("Failed to send guardian consent email for aluno %s", aluno.id)


def preparar_consentimento_responsavel(aluno: Aluno, email_responsavel: str | None) -> None:
    """Exige o e-mail do responsável e gera o token de consentimento do menor."""
    if not email_responsavel:
        raise ValidationError(
            "E-mail do responsável é obrigatório para menores de 18 anos",
            details={"field": "email_responsavel"},
        )
    aluno.email_responsavel = email_responsavel.strip().lower()
    aluno.guardian_token = secrets.token_urlsafe(32)


# ─── Guardian consent ──────────────────────────────────────────────────────────


def get_guardian_consent_info(token: str) -> Aluno:
    """Return public aluno info for the guardian consent screen (no auth)."""
    aluno = db.session.query(Aluno).filter_by(guardian_token=token).first()
    if not aluno:
        raise NotFoundError("Link de consentimento inválido ou já utilizado")
    return aluno


def record_guardian_consent(token: str) -> Aluno:
    """
    Record guardian consent and advance the aluno to PENDING_APPROVAL.

    Raises: NotFoundError, ValidationError, AppError
    """
    aluno = db.session.query(Aluno).filter_by(guardian_token=token).first()
    if not aluno:
        raise NotFoundError("Link de consentimento inválido ou já utilizado")

    if aluno.guardian_consented_at:
        raise ValidationError("Consentimento já registrado anteriormente")

    # Token expires 7 days after signup
    if aluno.created_at:
        expires_at = aluno.created_at + timedelta(days=7)
        if datetime.now(UTC) > expires_at:
            raise ValidationError("Este link expirou. Peça ao estudante que refaça o cadastro.")

    with transactional():
        aluno.guardian_consented_at = db.func.now()
        aluno.guardian_token = None  # single-use
        aluno.status = UserStatus.PENDING_APPROVAL
        db.session.flush()

        # Notify the gestor(s) of the prefeitura
        gestores = db.session.query(Gestor).filter_by(prefeitura_id=aluno.prefeitura_id).all()
        for gestor in gestores:
            NotificacaoService._criar_notificacao_interna(
                usuario_id=str(gestor.id),
                titulo="Novo cadastro aguardando aprovação",
                mensagem=(
                    f"O responsável do aluno {aluno.nome} autorizou o cadastro. "
                    "Acesse a tela Equipe para aprovar."
                ),
            )

    return aluno


# ─── Signup ────────────────────────────────────────────────────────────────────


def auto_cadastro(data: dict[str, Any]) -> Aluno:
    """
    Aluno se cadastra sozinho.
    - If minor (age < 18), requires email_responsavel; sends guardian consent email.
    - A prefeitura é inferida através da Instituição escolhida.

    Returns: Aluno object
    Raises: NotFoundError, ValidationError, AppError
    """
    inst_id = data.get("instituicao_id")
    instituicao = db.session.get(Instituicao, inst_id)
    if not instituicao:
        raise NotFoundError("Instituição não encontrada")

    prefeitura_id = instituicao.prefeitura_id
    if not prefeitura_id:
        raise NotFoundError("Prefeitura não encontrada")

    email = validate_email(data.get("email", ""))
    cpf_clean = validate_cpf(data.get("cpf", ""))

    if db.session.query(User).filter(User.email == email).first():
        raise ConflictError("Este e-mail já está cadastrado.", field="email")
    if db.session.query(User).filter(User.cpf == cpf_clean).first():
        raise ConflictError("Este CPF já está cadastrado.", field="cpf")

    with transactional():
        dados_endereco = data.get("endereco_casa")
        if not dados_endereco:
            raise ValidationError(
                "Endereço de casa é obrigatório", details={"field": "endereco_casa"}
            )

        password = validate_password(data.get("password", ""))

        ponto_casa = Ponto(
            prefeitura_id=prefeitura_id,
            latitude=dados_endereco.get("latitude"),
            longitude=dados_endereco.get("longitude"),
            apelido=f"Casa: {data.get('nome')}",
        )
        db.session.add(ponto_casa)
        db.session.flush()

        novo_end = Endereco(
            logradouro=dados_endereco.get("logradouro"),
            numero=dados_endereco.get("numero"),
            bairro=dados_endereco.get("bairro"),
            cidade=dados_endereco.get("cidade"),
            cep=dados_endereco.get("cep"),
            ponto_id=ponto_casa.id,
        )
        db.session.add(novo_end)

        novo_aluno = Aluno(
            prefeitura_id=prefeitura_id,
            nome=data.get("nome"),
            email=data.get("email"),
            senha_hash=generate_password_hash(password),
            cpf=data.get("cpf"),
            telefone=data.get("telefone"),
            role=UserRole.ALUNO,
            status=UserStatus.PENDING_SIGNUP,
            matricula=data.get("matricula"),
            instituicao_id=instituicao.id,
            ponto_casa_id=ponto_casa.id,
            nome_responsavel=data.get("nome_responsavel"),
            cpf_responsavel=data.get("cpf_responsavel"),
            data_nascimento=data.get("data_nascimento"),
        )

        db.session.add(novo_aluno)
        db.session.flush()  # get novo_aluno.id before checking is_minor

        if novo_aluno.is_minor:
            # Status stays PENDING_SIGNUP until guardian consents
            preparar_consentimento_responsavel(novo_aluno, data.get("email_responsavel"))

    if novo_aluno.is_minor:
        enviar_email_consentimento_responsavel(novo_aluno)

    return novo_aluno


_CAMPOS_PERFIL = ("nome", "telefone", "matricula", "nome_responsavel", "cpf_responsavel")


def _campos_de_endereco(dados_endereco: dict[str, Any]) -> dict[str, Any]:
    """Mapeia o payload de endereço para as colunas de `Endereco`.

    Estava escrito duas vezes dentro do `update_me`, uma para o caminho de
    atualização e outra para o de criação, com os mesmos cinco campos.
    """
    return {
        "logradouro": dados_endereco.get("logradouro"),
        "numero": dados_endereco.get("numero"),
        "bairro": dados_endereco.get("bairro"),
        "cidade": dados_endereco.get("cidade"),
        "cep": dados_endereco.get("cep"),
    }


def _atualizar_endereco_casa(aluno: Aluno, data: dict[str, Any]) -> None:
    """Atualiza o ponto de casa do aluno, criando-o quando ainda não existe."""
    dados_endereco = data["endereco_casa"]

    if not aluno.ponto_casa:
        novo_ponto = Ponto(
            prefeitura_id=aluno.prefeitura_id,
            latitude=dados_endereco.get("latitude"),
            longitude=dados_endereco.get("longitude"),
            apelido=f"Casa: {data.get('nome', aluno.nome)}",
        )
        db.session.add(novo_ponto)
        db.session.flush()
        db.session.add(Endereco(ponto_id=novo_ponto.id, **_campos_de_endereco(dados_endereco)))
        aluno.ponto_casa_id = novo_ponto.id
        return

    ponto_casa = cast(Ponto, aluno.ponto_casa)
    ponto_casa.latitude = dados_endereco.get("latitude")
    ponto_casa.longitude = dados_endereco.get("longitude")
    if "nome" in data:
        ponto_casa.apelido = f"Casa: {data['nome']}"

    endereco_bd = Endereco.query.filter_by(ponto_id=aluno.ponto_casa_id).first()
    if not endereco_bd:
        db.session.add(
            Endereco(ponto_id=aluno.ponto_casa_id, **_campos_de_endereco(dados_endereco))
        )
        return

    for coluna, valor in _campos_de_endereco(dados_endereco).items():
        setattr(endereco_bd, coluna, valor)


def _finalizar_cadastro_se_completo(aluno: Aluno, data: dict[str, Any], user_id: str) -> None:
    """Promove o aluno a ACTIVE quando o cadastro tem tudo que o app exige.

    Só vale para maior de idade em PENDING_SIGNUP: menor depende do
    consentimento do responsável, tratado em `record_guardian_consent`.
    """
    if aluno.status != UserStatus.PENDING_SIGNUP or aluno.is_minor:
        return

    faltando = []
    if not aluno.matricula and not data.get("matricula"):
        faltando.append("matricula")
    if not aluno.instituicao_id and not data.get("instituicao_id"):
        faltando.append("instituicao_id")

    dados_endereco = data.get("endereco_casa")
    if (
        not dados_endereco
        or dados_endereco.get("latitude") is None
        or dados_endereco.get("longitude") is None
    ):
        faltando.append("endereco_casa.latitude/longitude")

    if faltando:
        raise ValidationError(
            "Cadastro precisa ser finalizado antes de usar o app",
            details={"missing": faltando},
        )

    aluno.status = UserStatus.ACTIVE
    aluno.signup_completed_at = db.func.now()
    audit_logger.log_user_action(
        action="complete_signup",
        user_id=user_id,
        resource_type="aluno",
        resource_id=user_id,
    )


def update_me(user_id: str, data: dict[str, Any]) -> Aluno:
    """
    Atualiza perfil do aluno.

    Returns: Aluno object
    Raises: NotFoundError, ValidationError, AppError
    """
    aluno = db.session.get(Aluno, user_id)
    if not aluno:
        raise NotFoundError("Aluno não encontrado")

    with transactional():
        for field in _CAMPOS_PERFIL:
            if field in data:
                setattr(aluno, field, data[field])

        if "endereco_casa" in data:
            _atualizar_endereco_casa(aluno, data)

        _finalizar_cadastro_se_completo(aluno, data, user_id)

    return aluno


def delete_me(user_id: str) -> None:
    """
    Aluno se auto-exclui.

    Raises: NotFoundError, AppError
    """
    aluno = db.session.get(Aluno, user_id)
    if not aluno:
        raise NotFoundError("Aluno não encontrado")

    ponto_casa = cast(Ponto | None, aluno.ponto_casa)
    ponto_casa_id = ponto_casa.id if ponto_casa else None

    try:
        # A ordem importa: `aluno.ponto_casa_id` referencia `ponto.id` numa FK
        # sem ON DELETE, então o ponto só pode sair depois que a linha do aluno
        # deixar de apontar para ele. Os dependentes do aluno (rota_aluno,
        # alunos_confirmados, ocorrencia, notificacoes) são ON DELETE CASCADE.
        db.session.delete(aluno)
        db.session.flush()

        if ponto_casa is not None:
            try:
                # Savepoint: o ponto de casa pode ter sido reaproveitado como
                # parada de rota/viagem (FKs RESTRICT). Nesse caso ele não pode
                # ser removido — mas isso não pode impedir o aluno de excluir a
                # própria conta, então abortamos só a remoção do ponto.
                with db.session.begin_nested():
                    db.session.delete(ponto_casa)
            except IntegrityError:
                logger.warning(
                    "Ponto de casa %s mantido: ainda referenciado por outra entidade",
                    ponto_casa_id,
                )

        db.session.commit()

    except AppError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        logger.exception("Error deleting student account %s", user_id)
        raise AppError("Erro ao excluir conta", 500) from None


def get_aluno_by_id(gestor_id: str, aluno_id: str) -> Aluno:
    """
    Gestor retrieves full details for a single aluno.

    Raises: ForbiddenError, NotFoundError
    """
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem consultar alunos")
    aluno = db.session.get(Aluno, aluno_id)

    if not aluno:
        raise NotFoundError("Aluno não encontrado")
    if str(aluno.prefeitura_id) != str(gestor.prefeitura_id):
        raise ForbiddenError("Aluno não pertence à sua prefeitura")

    return aluno


def list_alunos_gestor(gestor_id: str, status: str | None = None) -> list[Aluno]:
    """
    Lista alunos da prefeitura (apenas para gestores).
    Optionally filter by status (e.g. 'PENDING_APPROVAL').

    Returns: List of Aluno objects
    Raises: ForbiddenError, ValidationError
    """
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem listar alunos")
    q = db.session.query(Aluno).filter_by(prefeitura_id=gestor.prefeitura_id)
    if status:
        try:
            status_enum = UserStatus[status]
        except KeyError:
            raise ValidationError(
                f"Status inválido. Valores válidos: {[s.value for s in UserStatus]}"
            ) from None
        q = q.filter(Aluno.status == status_enum)
    return q.all()


def aprovar_aluno(gestor_id: str, aluno_id: str) -> Aluno:
    """
    Gestor aprova um aluno com PENDING_APPROVAL, ativando sua conta.

    Returns: Aluno object
    Raises: ForbiddenError, NotFoundError, ValidationError
    """
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem aprovar alunos")
    aluno = db.session.get(Aluno, aluno_id)

    if not aluno:
        raise NotFoundError("Aluno não encontrado")
    if str(aluno.prefeitura_id) != str(gestor.prefeitura_id):
        raise ForbiddenError("Aluno não pertence à sua prefeitura")
    if aluno.status != UserStatus.PENDING_APPROVAL:
        raise ValidationError("Aluno não está aguardando aprovação")

    with transactional():
        aluno.status = UserStatus.ACTIVE
        aluno.signup_completed_at = db.func.now()
        db.session.flush()

        NotificacaoService._criar_notificacao_interna(
            usuario_id=str(aluno.id),
            titulo="Cadastro Aprovado!",
            mensagem=(
                "Seu cadastro foi aprovado pelo gestor. "
                "Você já pode confirmar presença nas viagens."
            ),
        )

        db.session.commit()
        audit_logger.log_user_action(
            action="aprovar_aluno",
            user_id=gestor_id,
            resource_type="aluno",
            resource_id=aluno_id,
        )
    return aluno
