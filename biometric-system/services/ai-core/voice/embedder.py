"""
Voice embedding via Resemblyzer (modèle GE2E, 256-D).

Resemblyzer est léger (~50MB), CPU-friendly, et produit des embeddings vocaux
comparables à ArcFace pour les visages (similarité cosinus → identité).

Pipeline:
    audio bytes (wav/mp3) → preprocess 16kHz mono → preprocess_wav() →
    encoder.embed_utterance() → embedding 256-D normalisé L2

Pour passer en prod sérieuse :
    - SpeechBrain ECAPA-TDNN (192-D, plus précis, plus lent)
    - WavLM / wav2vec2 (768-D, state-of-the-art, gros modèle)
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESEMBLYZER_OK = True
except ImportError:
    RESEMBLYZER_OK = False
    logger.warning("resemblyzer non installé — voice embedder en mode mock")


VOICE_EMBEDDING_DIM = 256


class VoiceEmbedder:
    """Encodeur vocal singleton (charge le modèle une fois)."""

    def __init__(self):
        self._encoder = None
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not RESEMBLYZER_OK:
            self._initialized = True
            return False
        try:
            self._encoder = VoiceEncoder(device="cpu", verbose=False)
            self._initialized = True
            logger.success("VoiceEncoder Resemblyzer chargé (256-D)")
            return True
        except Exception as e:
            logger.error(f"VoiceEncoder init: {e}")
            self._initialized = True
            return False

    def embed_bytes(self, audio_bytes: bytes, source_ext: str = "wav") -> Optional[np.ndarray]:
        """
        Génère un embedding vocal depuis un fichier audio en bytes.
        Supporte wav/mp3/flac (via soundfile/librosa).
        """
        if not self._initialized:
            self.initialize()

        if self._encoder is None:
            return self._mock_embedding()

        try:
            # Resemblyzer attend un path ou un array. On passe par un tempfile.
            with tempfile.NamedTemporaryFile(suffix=f".{source_ext}", delete=False) as tf:
                tf.write(audio_bytes)
                tmp_path = tf.name
            try:
                wav = preprocess_wav(Path(tmp_path))   # 16kHz mono normalisé
                if len(wav) < 16_000:                  # < 1 seconde
                    logger.debug("Audio trop court (< 1s)")
                    return None
                emb = self._encoder.embed_utterance(wav)
                return self.normalize(np.asarray(emb, dtype=np.float32))
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Voice embedding échec: {e}")
            return None

    @staticmethod
    def normalize(emb: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(emb)
        return emb / n if n > 0 else emb

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    @staticmethod
    def _mock_embedding() -> np.ndarray:
        emb = np.random.randn(VOICE_EMBEDDING_DIM).astype(np.float32)
        return emb / np.linalg.norm(emb)


_voice: Optional[VoiceEmbedder] = None


def get_voice_embedder() -> VoiceEmbedder:
    global _voice
    if _voice is None:
        _voice = VoiceEmbedder()
        _voice.initialize()
    return _voice
