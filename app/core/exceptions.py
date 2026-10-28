from typing import Any


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str = "APP_ERROR",
        field: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.field = field
        super().__init__(self.message)


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(self, message: str = "Recurso não encontrado"):
        super().__init__(message, 404, "NOT_FOUND")


class ValidationError(AppError):
    """Invalid input data (400)."""

    def __init__(self, message: str = "Dados inválidos", details: dict[str, Any] | None = None):
        super().__init__(message, 400, "VALIDATION_ERROR")
        self.details = details or {}


class ForbiddenError(AppError):
    """Access denied (403)."""

    def __init__(self, message: str = "Acesso negado"):
        super().__init__(message, 403, "FORBIDDEN")


class UnauthorizedError(AppError):
    """Not authenticated (401)."""

    def __init__(self, message: str = "Não autenticado"):
        super().__init__(message, 401, "UNAUTHORIZED")


class ConflictError(AppError):
    """Resource already exists or conflict (409)."""

    def __init__(self, message: str = "Recurso já existe", field: str | None = None):
        super().__init__(message, 409, "CONFLICT", field=field)


class RateLimitError(AppError):
    """Too many attempts (429)."""

    def __init__(self, message: str = "Muitas tentativas"):
        super().__init__(message, 429, "TOO_MANY_REQUESTS")
