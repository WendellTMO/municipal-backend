"""Feedback endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    feedback_request = api.model(
        "FeedbackRequest",
        {
            "tipo": fields.String(required=True, enum=["BUG", "SUGESTAO", "DUVIDA"]),
            "mensagem": fields.String(required=True, min_length=10, max_length=2000),
            "tela": fields.String(max_length=100, description="Tela onde o relato foi aberto"),
            "versao_app": fields.String(max_length=30),
            "plataforma": fields.String(enum=["android", "ios", "web"]),
            "dispositivo": fields.String(max_length=100, description="Modelo do aparelho ou navegador"),
            "versao_so": fields.String(max_length=40, description="Versão do sistema, ex.: Android 14"),
            "tamanho_tela": fields.String(description="Largura x altura da janela, ex.: 390x844"),
            "captura": fields.String(description="Imagem da tela em JPEG base64, até 400 KB"),
        },
    )

    feedback_response = api.model(
        "FeedbackResponse",
        {
            "id": fields.String(description="ID do relato"),
            "message": fields.String(example="Feedback registrado"),
        },
    )

    return {"feedback_request": feedback_request, "feedback_response": feedback_response}
