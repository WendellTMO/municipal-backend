# app/models/__init__.py
from .convite import Convite  # noqa: F401 (registra a tabela)
from .feedback import Feedback  # noqa: F401 — ensures table is registered
from .login_tentativa import LoginTentativa  # noqa: F401 (registra a tabela)
from .telemetria import EventoTelemetria  # noqa: F401 (registra a tabela)
from .ocorrencia import Ocorrencia  # noqa: F401 — ensures table is registered
