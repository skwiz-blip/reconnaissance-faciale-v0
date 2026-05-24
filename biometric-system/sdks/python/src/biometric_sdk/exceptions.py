class BiometricError(Exception):
    """Erreur de base du SDK."""


class AuthenticationError(BiometricError):
    """API key invalide ou révoquée (401)."""


class RateLimitError(BiometricError):
    """Quota tenant dépassé (429)."""


class ApiError(BiometricError):
    """Erreur HTTP générique (4xx/5xx)."""
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
