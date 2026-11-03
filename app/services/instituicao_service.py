"""Institution service - schools and universities management."""

import logging
import unicodedata
from typing import Any

from sqlalchemy import case, func, or_

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.transaction import transactional
from app.models.base import db
from app.models.enum import TipoInstituicao, UserRole
from app.models.geo import Endereco, Instituicao, Ponto
from app.models.prefeitura import Prefeitura
from app.models.user import User

logger = logging.getLogger(__name__)


def create_instituicao(gestor_id: str, data: dict[str, Any]) -> Instituicao:
    """
    Create a new institution (gestor only).

    Raises: ForbiddenError, ValidationError, AppError
    """
    user = db.session.get(User, gestor_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Permissão negada. Apenas gestores criam instituições.")

    nome = data.get("nome")
    cnpj = data.get("cnpj")
    tipo_str = data.get("tipo", "ESCOLA_PUBLICA")
    end_data = data.get("endereco")

    if not end_data:
        raise ValidationError("Dados de endereço são obrigatórios")

    with transactional():
        novo_ponto = Ponto(
            prefeitura_id=user.prefeitura_id,
            latitude=end_data.get("latitude"),
            longitude=end_data.get("longitude"),
            apelido=f"Inst: {nome}",
        )
        db.session.add(novo_ponto)
        db.session.flush()

        nova_inst = Instituicao(
            nome=nome,
            cnpj=cnpj,
            tipo=TipoInstituicao(tipo_str),
            ponto_id=novo_ponto.id,
        )
        db.session.add(nova_inst)

        novo_endereco = Endereco(
            logradouro=end_data.get("logradouro"),
            numero=end_data.get("numero"),
            bairro=end_data.get("bairro"),
            cidade=end_data.get("cidade"),
            cep=end_data.get("cep"),
            ponto_id=novo_ponto.id,
        )
        db.session.add(novo_endereco)

    return nova_inst


PALAVRAS_MAXIMAS_BUSCA = 6
# word_similarity de 0 a 1: abaixo disso o resultado parecido demais só atrapalha.
LIMIAR_PARECIDO = 0.5


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def _escapar_like(palavra: str) -> str:
    return palavra.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def buscar(user_id: str, termo: str, limite: int) -> list[Instituicao]:
    """Busca instituições da prefeitura do usuário por nome ou sigla.

    Sem diferenciar acento nem maiúscula; todas as palavras digitadas precisam aparecer, em qualquer
    ordem. A ordem do resultado: sigla igual ao texto, nome começando pelo texto, nome com uma palavra
    começando pela primeira digitada, o resto; empate pelo nome mais curto e depois alfabético. Sem
    resultado, tenta achar nomes parecidos (erro de digitação). Texto vazio devolve em ordem alfabética.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    palavras = _sem_acento(termo).split()[:PALAVRAS_MAXIMAS_BUSCA]
    da_prefeitura = Instituicao.prefeitura_id == user.prefeitura_id
    nome_n = func.unaccent(func.lower(Instituicao.nome))
    sigla_n = func.unaccent(func.lower(func.coalesce(Instituicao.sigla, "")))
    alvo = nome_n + " " + sigla_n

    if not palavras:
        return (
            Instituicao.query.filter(da_prefeitura).order_by(Instituicao.nome).limit(limite).all()
        )

    completo = " ".join(palavras)
    consulta = Instituicao.query.filter(da_prefeitura)
    for palavra in palavras:
        consulta = consulta.filter(alvo.like(f"%{_escapar_like(palavra)}%", escape="\\"))
    posicao = case(
        (sigla_n == completo, 0),
        (nome_n.like(f"{_escapar_like(completo)}%", escape="\\"), 1),
        (alvo.like(f"% {_escapar_like(palavras[0])}%", escape="\\"), 2),
        else_=3,
    )
    achadas = (
        consulta.order_by(posicao, func.length(Instituicao.nome), Instituicao.nome)
        .limit(limite)
        .all()
    )
    if achadas or len(completo) < 3:
        return achadas

    # Cada palavra precisa ser parecida com algo no nome: "universidde federal" acha, "universidade xyz" não.
    parecidas = Instituicao.query.filter(da_prefeitura)
    for palavra in palavras:
        parecidas = parecidas.filter(func.word_similarity(palavra, alvo) >= LIMIAR_PARECIDO)
    return (
        parecidas.order_by(func.word_similarity(completo, alvo).desc(), Instituicao.nome)
        .limit(limite)
        .all()
    )


def list_all(gestor_id: str) -> list[Instituicao]:
    """List all institutions for user's prefeitura."""
    user = db.session.get(User, gestor_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    return Instituicao.query.filter(Instituicao.prefeitura_id == user.prefeitura_id).all()


def list_all_public(filters: dict[str, Any]) -> list[Instituicao]:
    """List all institutions (public - for student registration)."""
    query = Instituicao.query.join(Prefeitura)

    search = filters.get("search")
    limit = filters.get("limit", 10)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Instituicao.nome.ilike(search_term),
                Instituicao.sigla.ilike(search_term),
                Instituicao.uf.ilike(search_term),
                Prefeitura.nome.ilike(search_term),
            )
        )

    query = query.order_by(Instituicao.nome.asc()).limit(limit)

    return query.all()


def get_by_id(gestor_id: str, inst_id: str) -> Instituicao:
    """
    Get institution by ID (with tenant check).

    Raises: NotFoundError, ForbiddenError
    """
    user = db.session.get(User, gestor_id)
    if not user:
        raise NotFoundError("Usuário não encontrado")

    inst = db.session.get(Instituicao, inst_id)
    if not inst:
        raise NotFoundError("Instituição não encontrada")

    if inst.ponto.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    return inst


def delete_instituicao(gestor_id: str, inst_id: str) -> None:
    """
    Delete an institution (gestor only).

    Raises: ForbiddenError, NotFoundError, AppError
    """
    user = db.session.get(User, gestor_id)
    if not user or user.role != UserRole.GESTOR:
        raise ForbiddenError("Apenas gestores podem remover instituições")

    inst = db.session.get(Instituicao, inst_id)
    if not inst:
        raise NotFoundError("Instituição não encontrada")

    if inst.ponto.prefeitura_id != user.prefeitura_id:
        raise ForbiddenError("Acesso negado")

    with transactional():
        db.session.delete(inst.ponto)
