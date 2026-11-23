"""Demo: o ônibus é localizado pelos celulares dos alunos a bordo, sem o app do motorista.

Só funciona com LOCALIZACAO_COLABORATIVA ligada no servidor. O envio do motorista não passa
por aqui. A posição fundida vai para os mesmos campos que o motorista usa, então o mapa e os
avisos de chegada dos outros alunos seguem como estão. As leituras individuais ficam na tabela
viagem_relato e são apagadas quando a viagem acaba (ou em até 1 hora depois do último envio).
"""

import logging
import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.base import db
from app.models.enum import StatusViagem, UserRole
from app.models.rota import RotaAluno
from app.models.user import User
from app.models.viagem import AlunosConfirmados, Viagem, ViagemPonto, ViagemRelato
from app.services import viagens_service
from app.services.notificacao_service import NotificacaoService
from app.utils.fusao_posicao import fundir_leituras, suavizar
from app.utils.geo_utils import calcular_distancia_metros

logger = logging.getLogger(__name__)

ANTES_DA_SAIDA = timedelta(minutes=30)
DEPOIS_DA_SAIDA = timedelta(hours=3)
# Leitura mais velha que isso não entra na fusão: o aluno parou de compartilhar ou desceu.
VALIDADE_DA_LEITURA = timedelta(seconds=30)
# Quem mandou algo neste prazo conta como "compartilhando agora".
JANELA_COMPARTILHANDO = timedelta(seconds=60)
RETENCAO = timedelta(hours=1)
INTERVALO_ENTRE_PEDIDOS = timedelta(minutes=3)
RAIO_CHEGADA_M = 60
PONTOS_A_FRENTE = 3
PRECISAO_PADRAO_M = 30


def ativa() -> bool:
    return os.getenv("LOCALIZACAO_COLABORATIVA", "").lower() in ("1", "true")


def _exigir_ativa() -> None:
    if not ativa():
        raise NotFoundError("Recurso indisponível")


def _aluno_e_viagem(user_id: str, viagem_id: str, travar: bool = False) -> tuple[User, Viagem]:
    aluno = db.session.get(User, user_id)
    if not aluno or aluno.role != UserRole.ALUNO:
        raise ForbiddenError("Acesso restrito a alunos")
    viagem = db.session.get(Viagem, viagem_id, with_for_update=travar, populate_existing=travar)
    if viagem is None or viagem.horario_rota is None:
        raise NotFoundError("Viagem não encontrada")
    inscrito = RotaAluno.query.filter_by(
        rota_id=viagem.horario_rota.rota_id, aluno_id=aluno.id
    ).first()
    if inscrito is None:
        raise ForbiddenError("Você não está inscrito na rota desta viagem")
    return aluno, viagem


def _esta_confirmado(viagem: Viagem, aluno: User) -> bool:
    confirmacao = db.session.get(AlunosConfirmados, (viagem.id, aluno.id))
    return confirmacao is not None and bool(confirmacao.confirmacao)


def _motivo_de_nao_compartilhar(viagem: Viagem, aluno: User) -> str | None:
    if not _esta_confirmado(viagem, aluno):
        return "Confirme a sua presença na viagem para compartilhar a localização."
    if viagem.status in (StatusViagem.CANCELADA, StatusViagem.FINALIZADA):
        return "Esta viagem não está ativa."
    saida = datetime.combine(viagem.data, viagem.horario_rota.horario_saida)
    agora = datetime.now()
    if agora < saida - ANTES_DA_SAIDA:
        return "Ainda é cedo: dá para compartilhar a partir de 30 minutos antes da saída."
    if agora > saida + DEPOIS_DA_SAIDA:
        return "O tempo para compartilhar esta viagem acabou."
    return None


def _ler_coordenadas(data: dict) -> tuple[float, float, float]:
    try:
        latitude = float(data["latitude"])
        longitude = float(data["longitude"])
        precisao = float(data.get("precisao") or PRECISAO_PADRAO_M)
    except (KeyError, TypeError, ValueError):
        raise ValidationError("Informe latitude, longitude e, se tiver, a precisão em metros")
    valores = (latitude, longitude, precisao)
    if not all(math.isfinite(v) for v in valores) or precisao <= 0:
        raise ValidationError("Coordenadas inválidas")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValidationError("Coordenadas fora do intervalo")
    return latitude, longitude, precisao


def _leituras_recentes(viagem: Viagem, agora: datetime) -> list[dict]:
    relatos = ViagemRelato.query.filter(
        ViagemRelato.viagem_id == viagem.id, ViagemRelato.recebido_em >= agora - VALIDADE_DA_LEITURA
    ).all()
    leituras = []
    for relato in relatos:
        leituras.append(
            {"lat": relato.latitude, "lon": relato.longitude, "precisao": relato.precisao_m}
        )
    return leituras


def _posicao_anterior(viagem: Viagem, agora: datetime) -> tuple[tuple[float, float] | None, float]:
    if viagem.motorista_lat is None or viagem.motorista_gps_hora is None:
        return None, 1e9
    anterior = (float(viagem.motorista_lat), float(viagem.motorista_lon))
    return anterior, (agora - viagem.motorista_gps_hora).total_seconds()


def _iniciar_se_preciso(viagem: Viagem, agora: datetime) -> None:
    if viagem.status != StatusViagem.AGENDADA:
        return
    viagem.status = StatusViagem.EM_ANDAMENTO
    viagem.inicio_real = agora
    try:
        avisados = {r.aluno_id for r in ViagemRelato.query.filter_by(viagem_id=viagem.id).all()}
        confirmados = AlunosConfirmados.query.filter_by(viagem_id=viagem.id, confirmacao=True).all()
        for conf in confirmados:
            if conf.aluno_id in avisados:
                continue
            NotificacaoService._criar_notificacao_interna(
                usuario_id=conf.aluno_id,
                titulo="🚌 O ônibus saiu",
                mensagem="Um colega começou a compartilhar a localização. Acompanhe no mapa.",
            )
    except Exception as erro:
        # Falha de aviso não pode impedir a viagem de começar.
        logger.error("Falha ao avisar o início colaborativo da viagem %s: %s", viagem.id, erro)


def _marcar_pontos_alcancados(
    viagem: Viagem, posicao: tuple[float, float], agora: datetime, primeira: bool
) -> None:
    """Marca como visitados os pontos que o ônibus alcançou, para o aviso seguir adiante."""
    pendentes = (
        ViagemPonto.query.filter_by(viagem_id=viagem.id, visitado=False)
        .order_by(ViagemPonto.ordem)
        .all()
    )
    if not pendentes:
        return

    def metros_ate(parada: ViagemPonto) -> float:
        return calcular_distancia_metros(
            posicao[0], posicao[1], float(parada.ponto.latitude), float(parada.ponto.longitude)
        )

    if primeira:
        # Quem começa a compartilhar no meio do percurso: o que ficou para trás conta como feito.
        mais_perto = min(pendentes, key=metros_ate)
        restantes = []
        for parada in pendentes:
            if parada.ordem < mais_perto.ordem:
                parada.visitado = True
                parada.origem_chegada = "colaborativo"
            else:
                restantes.append(parada)
        pendentes = restantes

    alcancada = None
    for parada in pendentes[:PONTOS_A_FRENTE]:
        if metros_ate(parada) <= RAIO_CHEGADA_M:
            alcancada = parada
    if alcancada is None:
        return
    for parada in pendentes:
        if parada.ordem <= alcancada.ordem:
            parada.visitado = True
            parada.origem_chegada = "colaborativo"
    alcancada.chegada_real = agora


def _finalizar_se_chegou(viagem: Viagem, agora: datetime) -> None:
    faltam = ViagemPonto.query.filter_by(viagem_id=viagem.id, visitado=False).count()
    if faltam > 0 or viagem.status != StatusViagem.EM_ANDAMENTO:
        return
    viagem.status = StatusViagem.FINALIZADA
    viagem.fim_real = agora
    viagem.km_real = viagens_service.calcular_km_percorrido(viagem.id)
    ViagemRelato.query.filter_by(viagem_id=viagem.id).delete()
    db.session.commit()


def enviar_relato(user_id: str, viagem_id: str, data: dict) -> dict[str, Any]:
    """Guarda a leitura do aluno, funde com as dos outros e atualiza a posição do ônibus."""
    _exigir_ativa()
    aluno, viagem = _aluno_e_viagem(user_id, viagem_id, travar=True)
    motivo = _motivo_de_nao_compartilhar(viagem, aluno)
    if motivo:
        raise ValidationError(motivo)
    latitude, longitude, precisao = _ler_coordenadas(data)
    agora = datetime.now(UTC)

    relato = db.session.get(ViagemRelato, (viagem.id, aluno.id))
    if relato is None:
        relato = ViagemRelato(viagem_id=viagem.id, aluno_id=aluno.id)
        db.session.add(relato)
    relato.latitude = latitude
    relato.longitude = longitude
    relato.precisao_m = precisao
    relato.recebido_em = agora
    ViagemRelato.query.filter(ViagemRelato.recebido_em < agora - RETENCAO).delete()
    db.session.flush()

    anterior, segundos = _posicao_anterior(viagem, agora)
    fundida = fundir_leituras(_leituras_recentes(viagem, agora), anterior)
    if fundida is None:
        db.session.commit()
        return {"aceito": False, "motivo": "precisao"}
    posicao = suavizar(anterior, (fundida[0], fundida[1]), fundida[2], segundos)
    if posicao is None:
        db.session.commit()
        return {"aceito": False, "motivo": "salto"}

    primeira = viagem.motorista_gps_hora is None
    _iniciar_se_preciso(viagem, agora)
    _marcar_pontos_alcancados(viagem, posicao, agora, primeira)
    resposta = viagens_service.registrar_posicao_da_viagem(
        viagem, posicao[0], posicao[1], agora, {}
    )
    _finalizar_se_chegou(viagem, agora)
    return {"aceito": True, "precisao_m": round(fundida[2], 1), **resposta}


def parar_relato(user_id: str, viagem_id: str) -> dict[str, str]:
    _exigir_ativa()
    aluno, viagem = _aluno_e_viagem(user_id, viagem_id)
    ViagemRelato.query.filter_by(viagem_id=viagem.id, aluno_id=aluno.id).delete()
    db.session.commit()
    return {"message": "Você parou de compartilhar a localização."}


def estado(user_id: str, viagem_id: str) -> dict[str, Any]:
    """O que a tela precisa para mostrar o botão e o aviso de que ninguém está compartilhando."""
    if not ativa():
        return {"ativa": False}
    aluno, viagem = _aluno_e_viagem(user_id, viagem_id)
    agora = datetime.now(UTC)
    recentes = ViagemRelato.query.filter(
        ViagemRelato.viagem_id == viagem.id, ViagemRelato.recebido_em >= agora - JANELA_COMPARTILHANDO
    ).all()
    eu_compartilhando = False
    for relato in recentes:
        if relato.aluno_id == aluno.id:
            eu_compartilhando = True
    sinal_ha = None
    if viagem.status == StatusViagem.EM_ANDAMENTO and viagem.motorista_gps_hora is not None:
        sinal_ha = int((agora - viagem.motorista_gps_hora).total_seconds())
    motivo = _motivo_de_nao_compartilhar(viagem, aluno)
    return {
        "ativa": True,
        "pode_compartilhar": motivo is None,
        "motivo": motivo,
        "compartilhando": len(recentes),
        "eu_compartilhando": eu_compartilhando,
        "em_andamento": viagem.status == StatusViagem.EM_ANDAMENTO,
        "sinal_ha_segundos": sinal_ha,
    }


def pedir_localizacao(user_id: str, viagem_id: str) -> dict[str, Any]:
    """Avisa os confirmados na viagem que alguém quer ver o ônibus. No máximo um pedido a cada 3 min."""
    _exigir_ativa()
    aluno, viagem = _aluno_e_viagem(user_id, viagem_id, travar=True)
    agora = datetime.now(UTC)
    ultimo = viagem.pedido_colaborativo_em
    if ultimo is not None and agora - ultimo < INTERVALO_ENTRE_PEDIDOS:
        db.session.commit()
        return {"avisados": 0, "motivo": "recente"}
    viagem.pedido_colaborativo_em = agora

    ja_compartilhando = {
        r.aluno_id
        for r in ViagemRelato.query.filter(
            ViagemRelato.viagem_id == viagem.id,
            ViagemRelato.recebido_em >= agora - JANELA_COMPARTILHANDO,
        ).all()
    }
    avisados = 0
    confirmados = AlunosConfirmados.query.filter_by(viagem_id=viagem.id, confirmacao=True).all()
    for conf in confirmados:
        if conf.aluno_id == aluno.id or conf.aluno_id in ja_compartilhando:
            continue
        NotificacaoService._criar_notificacao_interna(
            usuario_id=conf.aluno_id,
            titulo="📍 Onde está o ônibus?",
            mensagem=(
                "Um colega quer ver o ônibus no mapa. Se você está nele, abra o BusKá "
                "e toque em Compartilhar localização."
            ),
        )
        avisados += 1
    db.session.commit()
    return {"avisados": avisados}
