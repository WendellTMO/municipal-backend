from datetime import UTC, datetime

from app.models.enum import StatusViagem, UserRole
from app.models.notificacao import Notificacao
from app.models.user import Motorista
from app.models.viagem import AlunosConfirmados, Viagem
from app.services import viagens_service


def test_iniciar_viagem_notifica_apenas_confirmados(app, _db, prefeitura, aluno, horario_rota):
    with app.app_context():
        motorista = Motorista(
            prefeitura_id=prefeitura.id,
            nome="Motorista Teste",
            email="moto@test.com",
            senha_hash="123",
            cpf="11122233344",
            cnh="99988877766",
            role=UserRole.MOTORISTA,
        )
        _db.session.add(motorista)
        _db.session.flush()

        viagem = Viagem(
            data=datetime.now(UTC).date(),
            motorista_id=motorista.id,
            horario_rota_id=horario_rota.id,
            status=StatusViagem.AGENDADA,
        )
        _db.session.add(viagem)
        _db.session.flush()

        presenca_sim = AlunosConfirmados(
            viagem_id=viagem.id, aluno_id=aluno.user.id, confirmacao=True
        )
        _db.session.add(presenca_sim)
        _db.session.commit()

        viagens_service.controlar_viagem(
            user_id=str(motorista.id), viagem_id=str(viagem.id), data={"acao": "INICIAR"}
        )

        _db.session.refresh(viagem)
        assert viagem.status == StatusViagem.EM_ANDAMENTO

        notifs = Notificacao.query.filter_by(usuario_id=aluno.user.id).all()
        assert len(notifs) >= 1
