"""Telemetria endpoint documentation models."""

from flask_restx import fields


def register_models(api):
    contexto = api.model(
        "TelemetriaContexto",
        {
            "sessao_id": fields.String(required=True, description="Identificador da sessão do app, gerado no aparelho"),
            "versao_app": fields.String(),
            "plataforma": fields.String(enum=["android", "ios", "web"]),
            "dispositivo": fields.String(),
            "versao_so": fields.String(),
        },
    )
    evento = api.model(
        "TelemetriaEvento",
        {
            "tipo": fields.String(required=True, enum=["tela", "acao", "erro", "api", "gps", "sessao"]),
            "nome": fields.String(required=True, description="minúsculas, números e _ . : - /, até 80"),
            "props": fields.Raw(description="Chaves simples com número, texto curto ou booleano. Nunca dado pessoal."),
            "em": fields.Integer(description="Hora do evento no aparelho, em milissegundos desde 1970"),
        },
    )
    lote = api.model(
        "TelemetriaLote",
        {
            "contexto": fields.Nested(contexto, required=True),
            "eventos": fields.List(fields.Nested(evento), required=True, description="Até 50 por lote"),
        },
    )
    resposta = api.model(
        "TelemetriaResposta",
        {"aceitos": fields.Integer(), "descartados": fields.Integer()},
    )
    return {"telemetria_lote": lote, "telemetria_resposta": resposta}
