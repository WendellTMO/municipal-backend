"""Renova a agenda do banco de demonstração: viagens de hoje a hoje+6 e alunos confirmados.

Uso: DB_PORT=5434 DB_PASSWORD=... uv run python scripts/atualizar_agenda_demo.py
Idempotente: viagens que já existem não são recriadas. Recusa banco fora de localhost
a menos que receba --permitir-remoto.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.models.base import db  # noqa: E402
from app.models.enum import StatusViagem  # noqa: E402
from app.models.rota import DiasOperacao, HorarioRota, Rota, RotaAluno, RotaPonto  # noqa: E402
from app.models.user import Motorista  # noqa: E402
from app.models.viagem import Viagem  # noqa: E402
from app.services.viagens_service import (  # noqa: E402
    _get_dia_semana_enum,
    _popular_dados_da_viagem,
    confirmar_presenca_aluno,
)

DIAS_A_FRENTE = 7
HOSTS_LOCAIS = ("localhost", "127.0.0.1")
EMAIL_MOTORISTA_EM_ANDAMENTO = "carlos@buska.app"
ROTA_EM_ANDAMENTO = "Galante"
PREFIXOS_ROTAS_COM_CONFIRMADOS = ("Galante", "Bodocongó")
ALUNOS_CONFIRMADOS_POR_ROTA = 3


def _criar_viagens_que_faltam(hoje: date) -> int:
    """Uma viagem por horário e dia. Horário sem dias de operação roda todos os dias."""
    criadas = 0
    for horario in HorarioRota.query.all():
        rota = db.session.get(Rota, horario.rota_id)
        dias_de_operacao = DiasOperacao.query.filter_by(horario_rota_id=horario.id).all()
        dias_permitidos = []
        for dia in dias_de_operacao:
            dias_permitidos.append(dia.dia)

        for deslocamento in range(DIAS_A_FRENTE):
            data = hoje + timedelta(days=deslocamento)
            if dias_permitidos and _get_dia_semana_enum(data) not in dias_permitidos:
                continue
            existente = Viagem.query.filter_by(data=data, horario_rota_id=horario.id).first()
            if existente is not None:
                continue
            viagem = Viagem(
                data=data,
                horario_rota_id=horario.id,
                motorista_id=rota.motorista_padrao_id,
                veiculo_id=rota.veiculo_padrao_id,
                status=StatusViagem.AGENDADA,
            )
            db.session.add(viagem)
            db.session.flush()
            _popular_dados_da_viagem(viagem, rota)
            criadas += 1
    db.session.commit()
    return criadas


def _encerrar_em_andamento_vencidas(hoje: date) -> None:
    """Viagem que ficou EM_ANDAMENTO em dia passado atrapalha a tela do motorista."""
    vencidas = Viagem.query.filter(
        Viagem.status == StatusViagem.EM_ANDAMENTO, Viagem.data < hoje
    ).all()
    for viagem in vencidas:
        viagem.status = StatusViagem.FINALIZADA
        if viagem.inicio_real is not None:
            viagem.fim_real = viagem.inicio_real + timedelta(hours=2)
    db.session.commit()


def _iniciar_viagem_de_hoje(hoje: date, agora: datetime) -> str | None:
    """Deixa EM_ANDAMENTO a viagem de hoje da rota A (Carlos) mais próxima de agora."""
    carlos = Motorista.query.filter_by(email=EMAIL_MOTORISTA_EM_ANDAMENTO).first()
    if carlos is None:
        return None

    viagens = Viagem.query.filter_by(data=hoje, motorista_id=carlos.usuario_id).all()
    escolhida = None
    menor_distancia = None
    for viagem in viagens:
        if viagem.status == StatusViagem.EM_ANDAMENTO:
            if viagem.horario_rota.rota.nome.startswith(ROTA_EM_ANDAMENTO):
                return str(viagem.id)
            continue
        if viagem.status != StatusViagem.AGENDADA or viagem.horario_rota is None:
            continue
        if not viagem.horario_rota.rota.nome.startswith(ROTA_EM_ANDAMENTO):
            continue
        saida = datetime.combine(hoje, viagem.horario_rota.horario_saida, tzinfo=agora.tzinfo)
        distancia = abs(saida - agora)
        if menor_distancia is None or distancia < menor_distancia:
            menor_distancia = distancia
            escolhida = viagem

    if escolhida is None:
        return None
    saida = datetime.combine(hoje, escolhida.horario_rota.horario_saida, tzinfo=agora.tzinfo)
    escolhida.status = StatusViagem.EM_ANDAMENTO
    escolhida.inicio_real = min(saida, agora)
    db.session.commit()
    return str(escolhida.id)


def _confirmar_alunos(hoje: date) -> int:
    """Confirma os primeiros alunos das rotas A e B, embarcando no primeiro ponto da rota."""
    confirmados = 0
    for prefixo in PREFIXOS_ROTAS_COM_CONFIRMADOS:
        rota = Rota.query.filter(Rota.nome.like(f"{prefixo}%")).first()
        if rota is None:
            continue
        primeiro_ponto = (
            RotaPonto.query.filter_by(rota_id=rota.id).order_by(RotaPonto.ordem.asc()).first()
        )
        inscricoes = (
            RotaAluno.query.filter_by(rota_id=rota.id).limit(ALUNOS_CONFIRMADOS_POR_ROTA).all()
        )
        viagens = (
            Viagem.query.join(HorarioRota, Viagem.horario_rota_id == HorarioRota.id)
            .filter(
                HorarioRota.rota_id == rota.id,
                Viagem.data >= hoje,
                Viagem.status.in_([StatusViagem.AGENDADA, StatusViagem.EM_ANDAMENTO]),
            )
            .all()
        )
        for inscricao in inscricoes:
            for viagem in viagens:
                try:
                    confirmar_presenca_aluno(
                        str(inscricao.aluno_id),
                        str(viagem.id),
                        {"confirmacao": True, "ponto_embarque_id": primeiro_ponto.ponto_id},
                    )
                except AppError as erro:
                    print(f"  aluno {inscricao.aluno_id} sem confirmação: {erro.message}")
                    break
                confirmados += 1
    return confirmados


def atualizar_agenda(hoje: date, agora: datetime) -> dict[str, Any]:
    antes = Viagem.query.count()
    _encerrar_em_andamento_vencidas(hoje)
    criadas = _criar_viagens_que_faltam(hoje)
    em_andamento = _iniciar_viagem_de_hoje(hoje, agora)
    confirmacoes = _confirmar_alunos(hoje)
    return {
        "viagens_antes": antes,
        "viagens_criadas": criadas,
        "viagem_em_andamento": em_andamento,
        "confirmacoes": confirmacoes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--permitir-remoto", action="store_true", help="aceita DB_HOST fora de localhost"
    )
    args = parser.parse_args(argv)

    host = os.getenv("DB_HOST", "localhost")
    if host not in HOSTS_LOCAIS and not args.permitir_remoto:
        print(f"Recusado: DB_HOST={host} não é local. Use --permitir-remoto.", file=sys.stderr)
        return 2

    app = create_app()
    with app.app_context():
        resultado = atualizar_agenda(date.today(), datetime.now().astimezone())
    print(resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
