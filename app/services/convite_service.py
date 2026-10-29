"""Convites de cadastro de aluno: o gestor pré-cadastra, o aluno conclui pelo link e PIN."""

import hashlib
import hmac
import logging
import os
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import current_app
from marshmallow.exceptions import ValidationError as MarshmallowValidationError
from sqlalchemy import update
from werkzeug.security import generate_password_hash

from app.core.authz import get_gestor_or_403
from app.core.exceptions import ConflictError, NotFoundError, RateLimitError, ValidationError
from app.core.transaction import transactional
from app.models.base import db
from app.models.convite import (
    ACEITO,
    CANCELADO,
    ENVIADO,
    EXPIRADO,
    PENDENTE,
    STATUS_DO_CONVITE,
    Convite,
)
from app.models.enum import UserRole, UserStatus
from app.models.geo import Instituicao
from app.models.rota import Rota, RotaAluno
from app.models.user import Aluno, User
from app.schemas.validators import validate_phone
from app.services import aluno_service
from app.utils import audit_logger, validate_cpf, validate_email, validate_password, validate_uuid
from app.utils.email_sender import mail_configurado, send_email
from app.utils.email_template import montar_email_html

logger = logging.getLogger(__name__)

LIMITE_LOTE = 500
VALIDADE_DIAS = 7
PIN_MAX_TENTATIVAS = 5
MAX_TENTATIVAS_ENVIO = 3
LIMITE_ENVIO_POR_EXECUCAO = 50

TERMOS_DE_USO_VERSAO = "demo-1"
TERMOS_DE_USO_TEXTO = (
    "Ao continuar, você concorda em usar o BusKá apenas para o transporte escolar e autoriza "
    "o uso dos seus dados (nome, e-mail, CPF, endereço) pelos gestores do transporte. "
    "Esta é a versão de demonstração."
)

ENDERECO_CAMPOS = {
    "obrigatorios": ["logradouro", "numero", "bairro", "cidade", "estado"],
    "opcionais": ["cep", "complemento"],
}

CONVITE_INVALIDO = "Convite inválido ou expirado"
PIN_BLOQUEADO = "Muitas tentativas de PIN. Peça o reenvio do convite ao gestor."


def _agora() -> datetime:
    return datetime.now(UTC)


# ─── Token e PIN: só o hash vai para o banco ───────────────────────────────────


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_pin(token: str, pin: str) -> str:
    """HMAC com o segredo da aplicação: um PIN de 6 dígitos não resiste a um hash simples."""
    chave = current_app.config["JWT_SECRET_KEY"].encode()
    return hmac.new(chave, f"{token}:{pin.strip()}".encode(), hashlib.sha256).hexdigest()


def gerar_token_e_pin(convite: Convite) -> tuple[str, str]:
    """Gera link e PIN novos, grava só os hashes e a validade. Chamado pelo job de envio."""
    token = secrets.token_urlsafe(32)
    pin = f"{secrets.randbelow(1_000_000):06d}"
    convite.token_hash = hash_token(token)
    convite.pin_hash = hash_pin(token, pin)
    convite.pin_tentativas = 0
    convite.expira_em = _agora() + timedelta(days=VALIDADE_DIAS)
    return token, pin


def _voltar_para_fila(convite: Convite) -> None:
    convite.status = PENDENTE
    convite.token_hash = None
    convite.pin_hash = None
    convite.expira_em = None
    convite.pin_tentativas = 0
    convite.envio_tentativas = 0
    convite.enviado_em = None


def _expirar_vencidos(prefeitura_id) -> None:
    db.session.execute(
        update(Convite)
        .where(
            Convite.prefeitura_id == prefeitura_id,
            Convite.status == ENVIADO,
            Convite.expira_em <= _agora(),
        )
        .values(status=EXPIRADO)
    )
    db.session.commit()


# ─── Gestor: criar em lote ─────────────────────────────────────────────────────


def _texto(item: dict[str, Any], campo: str) -> str | None:
    valor = item.get(campo)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValidationError(f"O campo {campo} deve ser texto")
    valor = valor.strip()
    if valor == "":
        return None
    return valor


def _ids_validos(modelo, itens: list[dict[str, Any]], campo: str, prefeitura_id) -> set[str]:
    """Ids citados no lote que existem na prefeitura, numa query só por tipo."""
    candidatos = []
    for item in itens:
        valor = item.get(campo)
        if not isinstance(valor, str):
            continue
        try:
            candidatos.append(validate_uuid(valor.strip(), campo))
        except ValidationError:
            continue
    ids: set[str] = set()
    if not candidatos:
        return ids
    linhas = (
        db.session.query(modelo.id)
        .filter(modelo.prefeitura_id == prefeitura_id, modelo.id.in_(candidatos))
        .all()
    )
    for linha in linhas:
        ids.add(str(linha[0]))
    return ids


def _id_opcional(item: dict[str, Any], campo: str, rotulo: str, validos: set[str]) -> str | None:
    valor = _texto(item, campo)
    if valor is None:
        return None
    valor = valor.lower()
    if valor not in validos:
        raise ValidationError(f"{rotulo} inválido")
    return valor


def _validar_item(item: dict[str, Any], validos: dict[str, set[str]]) -> dict[str, Any]:
    email = validate_email(_texto(item, "email") or "")

    nome = _texto(item, "nome")
    if nome is None:
        raise ValidationError("Nome é obrigatório")
    if len(nome) > 100:
        raise ValidationError("Nome deve ter no máximo 100 caracteres")

    telefone = _texto(item, "telefone")
    if telefone is not None:
        telefone = validate_phone(telefone)

    return {
        "email": email,
        "nome": nome,
        "telefone": telefone,
        "instituicao_id": _id_opcional(
            item, "instituicao_id", "Instituição", validos["instituicao_id"]
        ),
        "rota_id": _id_opcional(item, "rota_id", "Rota", validos["rota_id"]),
    }


def _linha(posicao: int, email: str, resultado: str, motivo: str = "", convite_id=None) -> dict:
    return {
        "linha": posicao,
        "email": email,
        "resultado": resultado,
        "motivo": motivo,
        "id": str(convite_id) if convite_id else None,
    }


def criar_convites(gestor_id: str, itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grava convites PENDENTES em lote. Uma linha com problema não impede as outras."""
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem convidar alunos")
    if len(itens) == 0:
        raise ValidationError("Envie ao menos um convite")
    if len(itens) > LIMITE_LOTE:
        raise ValidationError(f"O lote aceita no máximo {LIMITE_LOTE} convites")

    prefeitura_id = gestor.prefeitura_id
    gestor_uuid = gestor.id
    _expirar_vencidos(prefeitura_id)

    # Consultas em bloco: o custo em queries não cresce com o tamanho do lote.
    emails: list[str] = []
    for item in itens:
        if isinstance(item.get("email"), str):
            emails.append(item["email"].strip().lower())
    emails_com_conta: set[str] = set()
    for linha in db.session.query(User.email).filter(User.email.in_(emails)).all():
        emails_com_conta.add(linha[0])
    por_email: dict[str, Convite] = {}
    consulta = Convite.query.filter(
        Convite.prefeitura_id == prefeitura_id,
        Convite.email.in_(emails),
        Convite.status.in_([PENDENTE, ENVIADO, EXPIRADO]),
    )
    for existente in consulta.all():
        por_email[existente.email] = existente
    validos = {
        "instituicao_id": _ids_validos(Instituicao, itens, "instituicao_id", prefeitura_id),
        "rota_id": _ids_validos(Rota, itens, "rota_id", prefeitura_id),
    }

    resultados: list[dict[str, Any]] = []
    gravados: dict[str, Convite] = {}
    with transactional():
        for posicao, item in enumerate(itens, start=1):
            email_informado = ""
            if isinstance(item.get("email"), str):
                email_informado = item["email"]
            try:
                dados = _validar_item(item, validos)
            except ValidationError as erro:
                resultados.append(_linha(posicao, email_informado, "INVALIDO", erro.message))
                continue
            except MarshmallowValidationError as erro:
                motivo = str(erro.messages[0])
                resultados.append(_linha(posicao, email_informado, "INVALIDO", motivo))
                continue

            email = dados["email"]
            if email in emails_com_conta:
                resultados.append(_linha(posicao, email, "PULADO", "E-mail já possui conta"))
                continue

            convite = por_email.get(email)
            if convite is not None and convite.status != EXPIRADO:
                resultados.append(
                    _linha(posicao, email, "PULADO", "Já existe convite em aberto", convite.id)
                )
                continue

            if convite is None:
                convite = Convite(prefeitura_id=prefeitura_id, email=email)
                resultado = "CRIADO"
            else:
                resultado = "RENOVADO"
            convite.criado_por_id = gestor_uuid
            convite.nome = dados["nome"]
            convite.telefone = dados["telefone"]
            convite.instituicao_id = dados["instituicao_id"]
            convite.rota_id = dados["rota_id"]
            _voltar_para_fila(convite)
            db.session.add(convite)
            por_email[email] = convite
            gravados[email] = convite
            resultados.append(_linha(posicao, email, resultado))

        # O id do convite novo só existe depois do flush.
        db.session.flush()
        for linha in resultados:
            if linha["resultado"] in ("CRIADO", "RENOVADO"):
                linha["id"] = str(gravados[linha["email"]].id)

    audit_logger.log_user_action(
        action="criar_convites",
        user_id=gestor_id,
        resource_type="convite",
        details={"linhas": len(itens)},
    )
    return resultados


# ─── Gestor: listar, reenviar, cancelar ────────────────────────────────────────


def listar_convites(gestor_id: str, status: str | None = None) -> list[Convite]:
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem listar convites")
    if status is not None and status not in STATUS_DO_CONVITE:
        raise ValidationError(f"Status inválido. Use: {', '.join(STATUS_DO_CONVITE)}")

    _expirar_vencidos(gestor.prefeitura_id)
    consulta = Convite.query.filter_by(prefeitura_id=gestor.prefeitura_id)
    if status is not None:
        consulta = consulta.filter_by(status=status)
    return consulta.order_by(Convite.created_at.desc()).all()


def _convite_da_prefeitura(gestor, convite_id: str) -> Convite:
    convite = db.session.get(Convite, validate_uuid(convite_id, "Convite"))
    if convite is None or convite.prefeitura_id != gestor.prefeitura_id:
        raise NotFoundError("Convite não encontrado")
    return convite


def reenviar_convite(gestor_id: str, convite_id: str) -> Convite:
    """Volta o convite para a fila. O job gera link e PIN novos, e os antigos deixam de valer."""
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem reenviar convites")
    convite = _convite_da_prefeitura(gestor, convite_id)
    if convite.status in (ACEITO, CANCELADO):
        raise ConflictError("Este convite já foi aceito ou cancelado")

    with transactional():
        _voltar_para_fila(convite)

    audit_logger.log_user_action(
        action="reenviar_convite",
        user_id=gestor_id,
        resource_type="convite",
        resource_id=str(convite.id),
    )
    return convite


def cancelar_convite(gestor_id: str, convite_id: str) -> None:
    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem cancelar convites")
    convite = _convite_da_prefeitura(gestor, convite_id)
    if convite.status in (ACEITO, CANCELADO):
        raise ConflictError("Este convite já foi aceito ou cancelado")

    with transactional():
        convite.status = CANCELADO

    audit_logger.log_user_action(
        action="cancelar_convite",
        user_id=gestor_id,
        resource_type="convite",
        resource_id=str(convite.id),
    )


# ─── Aluno convidado: PIN e aceite ─────────────────────────────────────────────


def _convite_por_token(token: str) -> Convite:
    """Mesmo 404 para token inexistente, expirado, aceito ou cancelado."""
    convite = Convite.query.filter_by(token_hash=hash_token(token), status=ENVIADO).first()
    if convite is None or convite.expira_em is None or convite.expira_em <= _agora():
        raise NotFoundError(CONVITE_INVALIDO)
    return convite


def _conferir_pin(convite: Convite, token: str, pin: str) -> None:
    if convite.pin_tentativas >= PIN_MAX_TENTATIVAS:
        raise RateLimitError(PIN_BLOQUEADO)
    if hmac.compare_digest(convite.pin_hash or "", hash_pin(token, pin)):
        return

    # UPDATE atômico: requisições simultâneas não escapam da contagem.
    tentativas = db.session.execute(
        update(Convite)
        .where(Convite.id == convite.id)
        .values(pin_tentativas=Convite.pin_tentativas + 1)
        .returning(Convite.pin_tentativas)
    ).scalar_one()
    db.session.commit()
    restantes = PIN_MAX_TENTATIVAS - tentativas
    if restantes <= 0:
        raise RateLimitError(PIN_BLOQUEADO)
    raise ValidationError(
        f"PIN incorreto. Restam {restantes} tentativa(s).",
        details={"tentativas_restantes": restantes},
    )


def validar_pin(token: str, pin: str) -> dict[str, Any]:
    """Só depois do PIN correto devolve os dados do convite e os termos de uso."""
    convite = _convite_por_token(token)
    _conferir_pin(convite, token, pin)

    return {
        "nome": convite.nome,
        "email": convite.email,
        "telefone": convite.telefone,
        "instituicao_id": str(convite.instituicao_id) if convite.instituicao_id else None,
        "instituicao_nome": convite.instituicao.nome if convite.instituicao else None,
        "rota_id": str(convite.rota_id) if convite.rota_id else None,
        "rota_nome": convite.rota.nome if convite.rota else None,
        "endereco_campos": ENDERECO_CAMPOS,
        "termos_versao": TERMOS_DE_USO_VERSAO,
        "termos_texto": TERMOS_DE_USO_TEXTO,
    }


def aceitar_convite(token: str, dados: dict[str, Any]) -> Aluno:
    """Cria o Aluno a partir do convite. Maior de idade entra ACTIVE, menor aguarda o responsável."""
    convite = _convite_por_token(token)
    _conferir_pin(convite, token, dados["pin"])

    if dados.get("aceite_termos") is not True:
        raise ValidationError("É preciso aceitar os termos de uso")
    senha = validate_password(dados["senha"])
    cpf = validate_cpf(dados["cpf"])
    nascimento: date = dados["data_nascimento"]
    if nascimento > date.today():
        raise ValidationError("Data de nascimento inválida")
    telefone = dados.get("telefone") or convite.telefone
    if telefone:
        telefone = validate_phone(telefone)

    if User.query.filter_by(email=convite.email).first():
        raise ConflictError("Este e-mail já está cadastrado.", field="email")
    if User.query.filter_by(cpf=cpf).first():
        raise ConflictError("Este CPF já está cadastrado.", field="cpf")

    agora = _agora()
    with transactional():
        aluno = Aluno(
            prefeitura_id=convite.prefeitura_id,
            nome=convite.nome,
            email=convite.email,
            senha_hash=generate_password_hash(senha),
            cpf=cpf,
            telefone=telefone,
            role=UserRole.ALUNO,
            data_nascimento=nascimento,
            instituicao_id=convite.instituicao_id,
        )
        if aluno.is_minor:
            if not dados.get("nome_responsavel"):
                raise ValidationError(
                    "Nome do responsável é obrigatório para menores de 18 anos",
                    details={"field": "nome_responsavel"},
                )
            aluno.status = UserStatus.PENDING_SIGNUP
            aluno.nome_responsavel = dados["nome_responsavel"]
            aluno.cpf_responsavel = dados.get("cpf_responsavel")
            aluno_service.preparar_consentimento_responsavel(aluno, dados.get("email_responsavel"))
        else:
            aluno.status = UserStatus.ACTIVE
            aluno.signup_completed_at = agora
        db.session.add(aluno)
        db.session.flush()

        if convite.rota_id:
            db.session.add(RotaAluno(rota_id=convite.rota_id, aluno_id=aluno.id))
        aluno_service.gravar_endereco_de_moradia(aluno, dados["endereco"])

        convite.status = ACEITO
        convite.aceito_em = agora
        convite.termos_versao = TERMOS_DE_USO_VERSAO
        convite.aluno_id = aluno.id
        convite.pin_hash = None

    if aluno.is_minor:
        aluno_service.enviar_email_consentimento_responsavel(aluno)

    audit_logger.log_user_action(
        action="aceitar_convite",
        user_id=str(aluno.id),
        resource_type="convite",
        resource_id=str(convite.id),
    )
    return aluno


# ─── Envio do e-mail (chamado pelo job_convites) ───────────────────────────────


def _montar_email(convite: Convite, link: str, pin: str, frontend_url: str) -> tuple[str, str, str]:
    """Assunto, texto simples e HTML do convite."""
    assunto = "Seu convite para o BusKá"
    url_web = frontend_url.rstrip("/")
    url_apk = f"{url_web}/buska.apk"
    texto = (
        f"Olá, {convite.nome}!\n\n"
        "Você foi convidado(a) para usar o BusKá, o app do transporte escolar.\n"
        "Siga os passos abaixo.\n\n"
        "1. Conclua seu cadastro\n"
        "Abra o link e informe o código de acesso (PIN). O código é pessoal.\n"
        f"Link: {link}\n"
        f"Código de acesso (PIN): {pin}\n"
        f"O convite vale por {VALIDADE_DIAS} dias. "
        "Se você não esperava este e-mail, ignore esta mensagem.\n\n"
        "2. Baixe o app\n"
        f"Android: {url_apk}\n"
        "Ao instalar, o Android pode pedir para permitir a instalação de fontes desconhecidas.\n\n"
        "3. Abra o app e entre\n"
        "Entre com o e-mail e a senha que você criou no cadastro.\n\n"
        "No iPhone, o app chega em breve. "
        f"Por enquanto use o BusKá pelo navegador: {url_web}"
    )
    pagina = montar_email_html(
        titulo="Seu convite para o BusKá",
        preheader="Conclua seu cadastro no BusKá com o link e o código de acesso.",
        saudacao=f"Olá, {convite.nome}!",
        paragrafos=[
            "Você foi convidado(a) para usar o BusKá, o app do transporte escolar.",
            "Siga os passos abaixo para começar a usar.",
        ],
        botao_texto="Concluir meu cadastro",
        botao_url=link,
        pin=pin,
        validade=(
            f"O convite vale por {VALIDADE_DIAS} dias. "
            "Se você não esperava este e-mail, ignore esta mensagem."
        ),
        links_app=(url_apk, url_web),
    )
    return assunto, texto, pagina


def _desfazer_credenciais(convite: Convite) -> None:
    convite.token_hash = None
    convite.pin_hash = None
    convite.expira_em = None


def processar_envios() -> int:
    """Envia os convites PENDENTES: link e PIN novos a cada envio, só os hashes ficam salvos.

    Devolve quantos convites saíram da fila. Sem configuração de e-mail em produção,
    a fila fica intacta e nada de link ou PIN vai para o log.
    """
    frontend_url = (current_app.config.get("FRONTEND_URL") or "").strip()
    if frontend_url == "":
        logger.error("FRONTEND_URL vazio: convites continuam na fila.")
        return 0

    em_desenvolvimento = os.getenv("FLASK_ENV", "development") == "development"
    if not mail_configurado() and not em_desenvolvimento:
        logger.warning("E-mail não configurado: convites continuam na fila.")
        return 0

    pendentes = (
        Convite.query.filter(
            Convite.status == PENDENTE, Convite.envio_tentativas < MAX_TENTATIVAS_ENVIO
        )
        .order_by(Convite.created_at.asc())
        .limit(LIMITE_ENVIO_POR_EXECUCAO)
        .all()
    )

    enviados = 0
    for convite in pendentes:
        token, pin = gerar_token_e_pin(convite)
        link = f"{frontend_url.rstrip('/')}/convite/{token}"

        if mail_configurado():
            assunto, texto, pagina = _montar_email(convite, link, pin, frontend_url)
            try:
                send_email(
                    to=convite.email,
                    subject=assunto,
                    body_plain=texto,
                    body_html=pagina,
                    logo_inline=True,
                )
            except Exception:
                convite.envio_tentativas += 1
                _desfazer_credenciais(convite)
                db.session.commit()
                logger.exception("Falha ao enviar o convite %s", convite.id)
                continue
        else:
            logger.warning(
                "Desenvolvimento sem e-mail: convite de %s, link %s PIN %s",
                convite.email,
                link,
                pin,
            )

        convite.status = ENVIADO
        convite.enviado_em = _agora()
        db.session.commit()
        enviados += 1

    return enviados
