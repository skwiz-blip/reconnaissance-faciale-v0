"""Vérification HMAC des webhooks côté partenaire."""
from __future__ import annotations

import hashlib
import hmac
import time


def verify_webhook_signature(
    secret: str, payload: str, header_value: str,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Vérifie un header `X-Bio-Signature: t=<ts>,v1=<hmac_sha256(ts.body)>`.

        >>> body = request.body  # raw bytes/string
        >>> ok = verify_webhook_signature(SECRET, body, request.headers["x-bio-signature"])
    """
    try:
        parts = dict(p.split("=", 1) for p in header_value.split(","))
        ts = int(parts["t"])
        if abs(time.time() - ts) > tolerance_seconds:
            return False
        msg = f"{ts}.{payload}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts["v1"])
    except Exception:
        return False
