import logging

from sqlalchemy import case, func

from app.core.authz import get_gestor_or_403
from app.core.exceptions import AppError, NotFoundError
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.rota import HorarioRota, Rota
from app.models.viagem import AlunosConfirmados, TelemetriaViagem, Viagem, ViagemPonto

logger = logging.getLogger(__name__)


def obter_progresso_viagem(gestor_id: str, viagem_id: str) -> list[dict]:
    """Retorna os pontos pelos quais o motorista já passou, em ordem cronológica."""

    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem auditar o trajeto de viagens")

    viagem = (
        db.session.query(Viagem)
        .join(HorarioRota)
        .join(Rota)
        .filter(Viagem.id == viagem_id, Rota.prefeitura_id == gestor.prefeitura_id)
        .first()
    )

    if not viagem:
        raise NotFoundError("Viagem não encontrada ou não pertence à sua prefeitura")

    pontos_visitados = (
        ViagemPonto.query.filter(
            ViagemPonto.viagem_id == viagem_id, ViagemPonto.chegada_real.isnot(None)
        )
        .order_by(ViagemPonto.chegada_real.asc())
        .all()
    )

    return [
        {
            "ponto_id": str(vp.ponto_id),
            "apelido": vp.ponto.apelido,
            "horario_passagem": vp.chegada_real.isoformat() if vp.chegada_real else None,
        }
        for vp in pontos_visitados
    ]


def relatorio_periodo_gestor(gestor_id: str, data_inicio: str, data_fim: str) -> dict:
    """Gera inteligência de negócio agregada para o painel web do Gestor."""
    gestor = get_gestor_or_403(
        gestor_id, "Apenas gestores podem visualizar relatórios operacionais"
    )

    try:
        stats_viagem = (
            db.session.query(
                func.count(Viagem.id).label("total_viagens"),
                func.sum(Viagem.km_real).label("km_total_rodado"),
            )
            .join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
            .join(Rota, HorarioRota.rota_id == Rota.id)
            .filter(
                Rota.prefeitura_id == gestor.prefeitura_id,
                Viagem.data >= data_inicio,
                Viagem.data <= data_fim,
                Viagem.status == StatusViagem.FINALIZADA,
            )
            .first()
        )

        stats_alunos = (
            db.session.query(
                func.sum(case((AlunosConfirmados.embarcou.is_(True), 1), else_=0)).label(
                    "total_embarques"
                ),
                func.sum(
                    case(
                        (
                            (AlunosConfirmados.confirmacao.is_(True))
                            & (AlunosConfirmados.embarcou.is_(False)),
                            1,
                        ),
                        else_=0,
                    )
                ).label("total_desperdicio"),
            )
            .select_from(Viagem)
            .join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
            .join(Rota, HorarioRota.rota_id == Rota.id)
            .join(AlunosConfirmados, Viagem.id == AlunosConfirmados.viagem_id)
            .filter(
                Rota.prefeitura_id == gestor.prefeitura_id,
                Viagem.data >= data_inicio,
                Viagem.data <= data_fim,
                Viagem.status == StatusViagem.FINALIZADA,
                # Sem registro no app não há embarque medido: não entra na conta de vagas.
                Viagem.realizada_sem_app.is_(False),
            )
            .first()
        )
        total_viagens = int(stats_viagem.total_viagens or 0) if stats_viagem else 0
        km = float(stats_viagem.km_total_rodado or 0) if stats_viagem else 0.0

        embarques = int(stats_alunos.total_embarques or 0) if stats_alunos else 0
        desperdicio = int(stats_alunos.total_desperdicio or 0) if stats_alunos else 0

        return {
            "periodo": f"{data_inicio} até {data_fim}",
            "viagens_realizadas": total_viagens,
            "alunos_transportados": embarques,
            "vagas_desperdicadas": desperdicio,
            "km_total_rodado": km,
            "media_alunos_por_km": round(embarques / km, 2) if km > 0 else 0.0,
        }

    except Exception as e:
        logger.error(f"Erro ao gerar relatorio do gestor {gestor_id}: {e}")
        raise AppError("Erro ao processar relatório do período", 500)


def obter_telemetria_viagem(gestor_id: str, viagem_id: str) -> list[dict]:
    """Retorna o rastro de GPS (telemetria) de uma viagem em ordem cronológica."""

    gestor = get_gestor_or_403(gestor_id, "Apenas gestores podem auditar a telemetria de viagens")

    viagem = (
        db.session.query(Viagem)
        .join(HorarioRota)
        .join(Rota)
        .filter(Viagem.id == viagem_id, Rota.prefeitura_id == gestor.prefeitura_id)
        .first()
    )

    if not viagem:
        raise NotFoundError("Viagem não encontrada ou não pertence à sua prefeitura")

    rastros = (
        TelemetriaViagem.query.filter_by(viagem_id=viagem_id)
        .order_by(TelemetriaViagem.timestamp.asc())
        .all()
    )

    return [
        {
            "latitude": float(r.latitude),
            "longitude": float(r.longitude),
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rastros
    ]
