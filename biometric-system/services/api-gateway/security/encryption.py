"""
Chiffrement applicatif des embeddings biométriques (AES-256-GCM).

Pourquoi côté application (et pas pgcrypto) ?
  - Permet la recherche FAISS en clair en mémoire (FAISS ne sait pas indexer
    des bytes chiffrés). Les vecteurs sont déchiffrés UNE SEULE FOIS au boot
    pour alimenter FAISS, puis tournent en RAM ; le repos de la base reste
    chiffré.
  - Clé centralisée: rotation possible sans toucher PostgreSQL.
  - Format de stockage:
        TEXT base64( nonce(12) | ciphertext | tag(16) )
    dans la colonne `embedding_encrypted` (Phase 5).
    L'ancienne colonne `embedding` (vector) reste compatible si
    BIO_EMBEDDING_ENCRYPTION=false.

Sécurité:
  - Clé en variable d'env (Phase 5), à terme via KMS (AWS KMS / Vault).
  - Nonce 96 bits aléatoire par enregistrement → résistant aux collisions.
  - Auth tag 128 bits → détection d'altération.

Performance: ~1µs/embedding (CPU) — négligeable.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Optional

import numpy as np
from loguru import logger

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False
    logger.warning("cryptography non installé — chiffrement désactivé")


_NONCE_BYTES = 12          # 96 bits, recommandé pour GCM
_KEY_BYTES   = 32          # 256 bits


# ============================================================
# Gestion de clé
# ============================================================

_key: Optional[bytes] = None


def derive_key(secret: str, salt: str = "biometric.embedding.v1") -> bytes:
    """
    Dérive une clé 256 bits depuis le secret applicatif.
    Stable: même secret + même salt → même clé.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), salt.encode("utf-8"),
        iterations=200_000, dklen=_KEY_BYTES,
    )


def _load_key() -> Optional[bytes]:
    """
    Charge la clé depuis la configuration. Priorité:
      1. BIO_ENCRYPTION_KEY (32 bytes hex / base64) — direct
      2. SECRET_KEY (passphrase) — dérivée via PBKDF2
    """
    global _key
    if _key is not None:
        return _key
    if not CRYPTO_OK:
        return None

    from config import get_settings
    s = get_settings()
    if not s.embedding_encryption_enabled:
        return None

    raw = (s.embedding_encryption_key or "").strip()
    if raw:
        try:
            # Hex (64 chars) ou base64
            if len(raw) == 64:
                _key = bytes.fromhex(raw)
            else:
                _key = base64.b64decode(raw)
            if len(_key) != _KEY_BYTES:
                raise ValueError(f"Clé doit faire {_KEY_BYTES} bytes, reçu {len(_key)}")
            return _key
        except Exception as e:
            logger.error(f"BIO_ENCRYPTION_KEY invalide: {e} — fallback PBKDF2")

    # Fallback: dérivation depuis SECRET_KEY
    if not s.secret_key or s.secret_key == "change_me":
        logger.warning("SECRET_KEY trop faible — chiffrement embeddings non sûr en prod")
    _key = derive_key(s.secret_key)
    return _key


def is_encryption_enabled() -> bool:
    return _load_key() is not None


# ============================================================
# API bytes
# ============================================================

def encrypt_bytes(plaintext: bytes) -> str:
    """Chiffre arbitrary bytes → string base64 (nonce||ct||tag)."""
    key = _load_key()
    if key is None:
        raise RuntimeError("Chiffrement désactivé")
    aes = AESGCM(key)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_bytes(payload: str) -> bytes:
    """Inverse de encrypt_bytes()."""
    key = _load_key()
    if key is None:
        raise RuntimeError("Chiffrement désactivé")
    raw = base64.b64decode(payload)
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, None)


# ============================================================
# API embeddings (float32 array)
# ============================================================

def encrypt_embedding(embedding: np.ndarray) -> str:
    """
    Chiffre un embedding 512D float32 → string stockable en TEXT.
    L'embedding sera tojours sérialisé comme float32 little-endian.
    """
    arr = np.ascontiguousarray(embedding.astype(np.float32))
    return encrypt_bytes(arr.tobytes())


def decrypt_embedding(payload: str, dim: int = 512) -> np.ndarray:
    """Reconstitue l'array numpy depuis le payload chiffré."""
    raw = decrypt_bytes(payload)
    arr = np.frombuffer(raw, dtype=np.float32)
    if arr.size != dim:
        raise ValueError(f"Embedding inattendu: {arr.size} != {dim}")
    return arr


# ============================================================
# CLI utility (pour générer une clé)
# ============================================================

def generate_key_hex() -> str:
    """Génère une clé 256 bits hex (64 chars)."""
    return secrets.token_hex(_KEY_BYTES)


if __name__ == "__main__":
    # Permet: python -m security.encryption generate-key
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "generate-key":
        print(generate_key_hex())
    else:
        print("Usage: python -m security.encryption generate-key")
