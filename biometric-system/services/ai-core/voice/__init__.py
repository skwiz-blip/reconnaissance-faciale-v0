"""Reconnaissance vocale + fusion multimodale visage + voix."""
from voice.embedder import VoiceEmbedder, get_voice_embedder, VOICE_EMBEDDING_DIM
from voice.fusion import (
    fuse_face_voice, FusionResult, FUSION_DEFAULT_WEIGHTS,
)

__all__ = [
    "VoiceEmbedder", "get_voice_embedder", "VOICE_EMBEDDING_DIM",
    "fuse_face_voice", "FusionResult", "FUSION_DEFAULT_WEIGHTS",
]
