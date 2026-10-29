from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts.notificacao_contract import get_notificacao_input_model
from app.services.notificacao_service import NotificacaoService

api = Namespace("notificacoes", description="Avisos e comunicados")

notificacao_input_model = get_notificacao_input_model(api)


@api.route("/")
class NotificacaoListResource(Resource):
    @api.doc("listar_minhas_notificacoes")
    @jwt_required()
    def get(self):
        """Lista as notificações do usuário logado"""
        user_id = get_jwt_identity()
        notificacoes = NotificacaoService.listar_notificacoes(user_id)
        return [
            {
                "id": str(n.id),
                "titulo": n.titulo,
                "mensagem": n.mensagem,
                "enviada": n.enviada,
                "data_envio": str(n.data_envio),
            }
            for n in notificacoes
        ], 200

    @api.doc("gestor_enviar_notificacao")
    @api.expect(notificacao_input_model, validate=True)
    @jwt_required()
    def post(self):
        """(Gestor) Envia um aviso para Rota ou Viagem"""
        user_id = get_jwt_identity()
        data = request.get_json()
        return NotificacaoService.notificar_por_gestor(user_id, data), 201

    @api.doc("excluir_minhas_notificacoes")
    @jwt_required()
    def delete(self):
        """Exclui todas as notificações do usuário logado"""
        user_id = get_jwt_identity()
        return NotificacaoService.excluir_todas(user_id), 200


@api.route("/<string:id>/lida")
class NotificacaoLidaResource(Resource):
    @api.doc("marcar_notificacao_lida")
    @jwt_required()
    def patch(self, id):
        """Marca uma notificação como lida"""
        user_id = get_jwt_identity()
        return NotificacaoService.marcar_lida(user_id, id), 200


@api.route("/<string:id>")
class NotificacaoResource(Resource):
    @api.doc("excluir_notificacao")
    @jwt_required()
    def delete(self, id):
        """Exclui uma notificação do usuário logado"""
        user_id = get_jwt_identity()
        return NotificacaoService.excluir(user_id, id), 200
