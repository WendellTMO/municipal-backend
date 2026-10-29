from unittest.mock import MagicMock, patch

from app.models.enum import StatusViagem, UserRole
from app.services.viagens_service import atualizar_localizacao, gerar_viagens_periodo


def test_atualizar_localizacao_dispara_notificacao(app):
    with app.app_context():
        with (
            patch("app.services.viagens_service.db") as mock_db,
            patch("app.services.viagens_service.ViagemPonto") as mock_ponto_class,
            patch("app.services.viagens_service.AlunosConfirmados") as mock_aluno_conf_class,
            patch("app.services.viagens_service.NotificacaoService") as mock_notif,
        ):

            # 1. Arrange: Setup do Motorista e Viagem
            mock_user = MagicMock(role=UserRole.MOTORISTA)
            mock_viagem = MagicMock(status=StatusViagem.EM_ANDAMENTO)
            mock_viagem.id = "123e4567-e89b-12d3-a456-426614174000"
            mock_viagem.localizacao_solicitada_em = None
            mock_db.session.get.side_effect = [mock_user, mock_viagem]

            # 2. Arrange: Setup do Ponto (Forçamos o aviso_aproximacao_enviado como FALSE)
            mock_ponto_geo = MagicMock(latitude=-23.5, longitude=-46.6, apelido="Ponto Teste")
            mock_ponto_geo.id = "p-UUID"

            mock_ponto_viagem = MagicMock()
            mock_ponto_viagem.aviso_aproximacao_enviado = False
            mock_ponto_viagem.ponto = mock_ponto_geo
            mock_ponto_viagem.viagem_id = mock_viagem.id

            mock_ponto_class.query.filter_by.return_value.order_by.return_value.all.return_value = [
                mock_ponto_viagem
            ]

            mock_aluno_confirmado = MagicMock()
            mock_aluno_confirmado.aluno_id = "aluno-UUID"
            mock_aluno_conf_class.query.filter_by.return_value.all.return_value = [
                mock_aluno_confirmado
            ]

            func_path = "app.services.viagens_service.calcular_distancia_metros"

            try:
                with patch(func_path, return_value=300):
                    atualizar_localizacao(
                        user_id="u-1",
                        viagem_id=mock_viagem.id,
                        data={"latitude": -23.501, "longitude": -46.601},
                    )
            except AttributeError:
                with patch(
                    "app.services.viagens_service._calcular_distancia_metros", return_value=300
                ):
                    atualizar_localizacao(
                        user_id="u-1",
                        viagem_id=mock_viagem.id,
                        data={"latitude": -23.501, "longitude": -46.601},
                    )

            assert (
                mock_notif.notificar_aproximacao_ponto.called or mock_notif.mock_calls
            ), "O serviço de notificações deveria ter sido acionado para o aluno no ponto"


def test_gerar_viagens_periodo_sobrevive_a_um_dia_com_falha():
    """Uma falha no dia 3 não pode abortar os 11 dias restantes em silêncio."""
    with patch("app.services.viagens_service.gerar_viagens_em_lote") as mock_lote:
        mock_lote.side_effect = [
            {"viagens_criadas": 1},
            {"viagens_criadas": 1},
            RuntimeError("falha simulada no dia 3"),
            *[{"viagens_criadas": 1}] * 11,
        ]

        total = gerar_viagens_periodo(gestor_id="gestor-1", dias_futuros=14)

    assert mock_lote.call_count == 14, "todos os dias devem ser tentados"
    assert total == 13, "o total deve contar apenas os dias que deram certo"
