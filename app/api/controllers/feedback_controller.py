from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource

from app.api.contracts import feedback_contract
from app.schemas.feedback_schema import FeedbackCreateRequestSchema
from app.services import feedback_service

api = Namespace("feedback", description="Relatos dos beta-testers (bug, sugestão, dúvida)")

models = feedback_contract.register_models(api)

feedback_create_request_schema = FeedbackCreateRequestSchema()

USER_AGENT_MAX = 300


@api.route("")
class FeedbackResource(Resource):
    @api.doc(
        "criar_feedback",
        responses={201: "Feedback registrado", 400: "Validation error", 401: "Unauthorized"},
    )
    @api.expect(models["feedback_request"])
    @api.response(201, "Feedback registrado", models["feedback_response"])
    @jwt_required()
    def post(self) -> tuple[dict[str, Any], int]:
        """Registra um relato do usuário logado"""
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        payload = feedback_create_request_schema.load(data)
        user_agent = request.headers.get("User-Agent", "")[:USER_AGENT_MAX] or None

        feedback = feedback_service.create_feedback(user_id, payload, user_agent)
        return {"id": str(feedback.id), "message": "Feedback registrado"}, 201
