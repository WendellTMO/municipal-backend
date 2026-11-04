import logging
from datetime import datetime, timedelta
from typing import Any

from app.extensions import scheduler
from app.models.base import db
from app.models.enum import StatusViagem
from app.models.rota import RotaAluno
from app.models.user import Aluno, User
from app.models.viagem import AlunosConfirmados, Viagem
from app.services.notificacao_service import NotificacaoService

logger = logging.getLogger(__name__)

# Antecedência dos lembretes. O aluno recebe o primeiro 10 horas antes da saída (uma viagem das 5h
# avisa às 19h do dia anterior) e o segundo 10 minutos antes.
ANTECEDENCIA_LEMBRETE = timedelta(hours=10)
ANTECEDENCIA_AVISO_FINAL = timedelta(minutes=10)


def _inicio_da_viagem(viagem: Any) -> datetime:
    """Data e hora de saída da viagem, no fuso do servidor (o mesmo de datetime.now())."""
    return datetime.combine(viagem.data, viagem.horario_rota.horario_saida)


def verificar_viagens_24h(agora: datetime | None = None):
    """Job: lembra os alunos da rota 10 horas antes da saída.

    O nome é histórico (era 24 horas): o job e a coluna `aviso_24h_enviado` mantêm o nome para o
    jobstore persistido continuar achando a função.
    """
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return

    with app.app_context():
        agora = agora or datetime.now()
        limite = agora + ANTECEDENCIA_LEMBRETE

        viagens = Viagem.query.filter(
            Viagem.status == StatusViagem.AGENDADA,
            Viagem.aviso_24h_enviado.is_(False),
            Viagem.data >= agora.date(),
            Viagem.data <= limite.date(),
        ).all()

        for viagem in viagens:
            if not viagem.horario_rota:
                continue
            inicio = _inicio_da_viagem(viagem)
            # Só avisa dentro das 10 horas que antecedem a saída. Viagem que já saiu não avisa.
            if inicio <= agora or inicio > limite:
                continue
            hora = inicio.strftime("%H:%M")
            inscricoes = RotaAluno.query.filter_by(rota_id=viagem.horario_rota.rota_id).all()

            for insc in inscricoes:
                aluno = db.session.get(User, insc.aluno_id)
                if aluno and getattr(aluno, "receber_notificacoes", True):
                    NotificacaoService._criar_notificacao_interna(
                        usuario_id=aluno.id,
                        titulo="⏰ Lembrete de Viagem",
                        mensagem=(
                            f"A sua viagem sai às {hora}, daqui a cerca de 10 horas. "
                            "Não se esqueça de confirmar a sua presença!"
                        ),
                    )

            viagem.aviso_24h_enviado = True

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro no Job de 24h: {e}")


def verificar_viagens_10min(agora: datetime | None = None):
    """Job: 10 minutos antes da saída, avisa o motorista (com a lista de universidades) e os
    alunos que confirmaram presença."""
    app = scheduler.app
    if not app:
        logger.error("Erro fatal: Instância do Flask (app) não encontrada no Scheduler.")
        return

    with app.app_context():
        agora = agora or datetime.now()

        viagens = Viagem.query.filter(
            Viagem.status == StatusViagem.AGENDADA,
            Viagem.aviso_10min_enviado.is_(False),
            Viagem.data == agora.date(),
        ).all()

        for viagem in viagens:
            if not viagem.horario_rota:
                continue
            falta = _inicio_da_viagem(viagem) - agora
            # O job roda de 10 em 10 minutos: a viagem entra na janela uma vez, e a flag evita repetir.
            if falta <= timedelta(0) or falta > ANTECEDENCIA_AVISO_FINAL:
                continue
            confirmados = AlunosConfirmados.query.filter_by(
                viagem_id=viagem.id, confirmacao=True
            ).all()

            universidades = set()
            for conf in confirmados:
                aluno = db.session.get(Aluno, conf.aluno_id)

                if aluno and getattr(aluno, "instituicao", None):
                    universidades.add(aluno.instituicao.nome)

            lista_univ = ", ".join(universidades) if universidades else "Nenhum aluno confirmado"

            NotificacaoService._criar_notificacao_interna(
                usuario_id=viagem.motorista_id,
                titulo="🚌 Viagem a iniciar em 10 minutos",
                mensagem=f"Prepare-se! As paragens universitárias desta viagem serão: {lista_univ}.",
            )

            hora = _inicio_da_viagem(viagem).strftime("%H:%M")
            for conf in confirmados:
                aluno_user = db.session.get(User, conf.aluno_id)
                if aluno_user and getattr(aluno_user, "receber_notificacoes", True):
                    NotificacaoService._criar_notificacao_interna(
                        usuario_id=aluno_user.id,
                        titulo="🚌 Seu ônibus sai em 10 minutos",
                        mensagem=f"A viagem sai às {hora}. Vá para o seu ponto de embarque!",
                    )

            viagem.aviso_10min_enviado = True

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro no Job de 10min: {e}")
