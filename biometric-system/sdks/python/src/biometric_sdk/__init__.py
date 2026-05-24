"""
SDK Python officiel — Biometric Recognition System.

    >>> from biometric_sdk import BiometricClient
    >>> client = BiometricClient(api_url="https://api.example.com",
    ...                          api_key="bio_xxx")
    >>> resp = client.recognize_from_file("photo.jpg")
    >>> print(resp.matches)
"""
from biometric_sdk.client import BiometricClient, AsyncBiometricClient
from biometric_sdk.models import (
    RecognizeResponse, Match, KYCResponse, AccessCheckResponse,
)
from biometric_sdk.exceptions import (
    BiometricError, AuthenticationError, RateLimitError, ApiError,
)
from biometric_sdk.webhooks import verify_webhook_signature

__version__ = "1.0.0"
__all__ = [
    "BiometricClient", "AsyncBiometricClient",
    "RecognizeResponse", "Match", "KYCResponse", "AccessCheckResponse",
    "BiometricError", "AuthenticationError", "RateLimitError", "ApiError",
    "verify_webhook_signature",
]
