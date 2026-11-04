"""Testes unitários para as tarefas de notificação em background."""

from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from app.tasks.notificacao_tasks import verificar_viagens_24h


def test_verificar_viagens_24h(app):
    """Testa se a task de 24h roda sem erros e aciona o serviço de notificações."""
    with app.app_context():

        with (
            patch("app.tasks.notificacao_tasks.Viagem.query") as mock_query,
            patch("app.tasks.notificacao_tasks.RotaAluno.query") as mock_rota_query,
            patch("app.tasks.notificacao_tasks.db.session.get") as mock_db_get,
            patch("app.tasks.notificacao_tasks.NotificacaoService") as mock_notificacao_service,
            patch("app.tasks.notificacao_tasks.scheduler") as mock_scheduler,
        ):

            mock_scheduler.app = app

            mock_viagem = MagicMock()
            mock_viagem.id = "viagem-123"
            mock_viagem.data = date(2026, 11, 4)
            mock_viagem.horario_rota.horario_saida = time(20, 0)
            mock_query.filter.return_value.all.return_value = [mock_viagem]

            mock_inscricao = MagicMock()
            mock_inscricao.aluno_id = "aluno-123"
            mock_rota_query.filter_by.return_value.all.return_value = [mock_inscricao]

            mock_aluno = MagicMock()
            mock_aluno.id = "aluno-123"
            mock_db_get.return_value = mock_aluno

            verificar_viagens_24h(agora=datetime(2026, 11, 4, 12, 0))

            assert (
                mock_notificacao_service.mock_calls
            ), "O serviço de notificações deveria ter sido chamado!"


def test_verificar_viagens_10min(app):
    """Testa se a task de 10 minutos roda sem erros e aciona o serviço de notificações."""
    with app.app_context():
        from app.tasks.notificacao_tasks import verificar_viagens_10min

        with (
            patch("app.tasks.notificacao_tasks.Viagem.query") as mock_query,
            patch("app.tasks.notificacao_tasks.AlunosConfirmados.query") as mock_alunos_query,
            patch("app.tasks.notificacao_tasks.db.session.get") as mock_db_get,
            patch("app.tasks.notificacao_tasks.NotificacaoService") as mock_notificacao_service,
            patch("app.tasks.notificacao_tasks.scheduler") as mock_scheduler,
        ):

            mock_scheduler.app = app

            mock_viagem = MagicMock()
            mock_viagem.id = "viagem-123"
            mock_viagem.data = date(2026, 11, 4)
            mock_viagem.horario_rota.horario_saida = time(12, 5)
            mock_query.filter.return_value.all.return_value = [mock_viagem]

            mock_confirmado = MagicMock()
            mock_confirmado.aluno_id = "aluno-123"
            mock_alunos_query.filter_by.return_value.all.return_value = [mock_confirmado]

            mock_aluno = MagicMock()
            mock_aluno.instituicao.nome = "Universidade Teste"
            mock_db_get.return_value = mock_aluno

            verificar_viagens_10min(agora=datetime(2026, 11, 4, 12, 0))

            assert (
                mock_notificacao_service.mock_calls
            ), "O serviço de notificações deveria ter sido chamado!"
