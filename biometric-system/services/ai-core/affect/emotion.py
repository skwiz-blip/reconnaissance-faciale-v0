"""
Analyse d'émotion via FER+ (Microsoft) — 8 émotions Ekman + neutre.

Modèle ONNX léger (~10MB), input 64x64 grayscale.
Output 8 logits → softmax → probabilités.

Si le modèle n'est pas disponible (model_dir vide), fallback heuristique
basé sur les landmarks géométriques (sourire ↔ happy, sourcils ↔ angry).

Modèle conseillé:
    https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus
    → emotion-ferplus-8.onnx (44 MB)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

try:
    import onnxruntime as ort
    ONNX_OK = True
except ImportError:
    ONNX_OK = False


EMOTION_LABELS = [
    "neutral", "happiness", "surprise", "sadness",
    "anger", "disgust", "fear", "contempt",
]


@dataclass(slots=True)
class EmotionResult:
    top_emotion:    str
    confidence:     float
    distribution:   dict[str, float] = field(default_factory=dict)
    source:         str = "fer_onnx"   # "fer_onnx" | "heuristic"


class EmotionAnalyzer:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._session = None
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not ONNX_OK or not self.model_path:
            self._initialized = True
            return False
        path = Path(self.model_path)
        if not path.exists():
            logger.info(f"FER+ model absent ({self.model_path}) — heuristique landmarks")
            self._initialized = True
            return False
        try:
            from gpu_runtime import providers_for
            from config import get_settings
            providers = providers_for(get_settings().gpu_enabled)
            self._session = ort.InferenceSession(self.model_path, providers=providers)
            self._initialized = True
            logger.success(f"FER+ chargé: {self.model_path}")
            return True
        except Exception as e:
            logger.error(f"FER+ load: {e}")
            self._initialized = True
            return False

    def analyze(
        self,
        face_img: np.ndarray,
        landmarks: Optional[np.ndarray] = None,
    ) -> EmotionResult:
        if not self._initialized:
            self.initialize()
        if self._session is not None:
            try:
                return self._analyze_onnx(face_img)
            except Exception as e:
                logger.warning(f"FER+ inférence: {e} → fallback heuristique")
        return self._analyze_heuristic(face_img, landmarks)

    # ----- ONNX -----
    def _analyze_onnx(self, face_img: np.ndarray) -> EmotionResult:
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if face_img.ndim == 3 else face_img
        gray = cv2.resize(gray, (64, 64)).astype(np.float32)
        # FER+ attend (1, 1, 64, 64)
        x = gray[None, None, :, :]
        name = self._session.get_inputs()[0].name
        logits = self._session.run(None, {name: x})[0][0]
        # softmax stable
        e = np.exp(logits - np.max(logits))
        probs = e / e.sum()
        idx = int(np.argmax(probs))
        return EmotionResult(
            top_emotion=EMOTION_LABELS[idx],
            confidence=float(probs[idx]),
            distribution={
                EMOTION_LABELS[i]: float(probs[i]) for i in range(len(EMOTION_LABELS))
            },
            source="fer_onnx",
        )

    # ----- Heuristique landmarks (fallback) -----
    @staticmethod
    def _analyze_heuristic(
        face_img: np.ndarray, landmarks: Optional[np.ndarray]
    ) -> EmotionResult:
        """
        Heuristique grossière sans modèle entraîné:
          - mouth width / eye width → happiness
          - eye openness → surprise / fear
          - sinon → neutral
        """
        if landmarks is None or len(landmarks) < 5:
            return EmotionResult(
                top_emotion="neutral", confidence=0.5,
                distribution={"neutral": 1.0}, source="heuristic",
            )
        try:
            eye_w = float(np.linalg.norm(landmarks[1] - landmarks[0])) + 1e-6
            mouth_w = float(np.linalg.norm(landmarks[4] - landmarks[3]))
            ratio = mouth_w / eye_w
            if ratio > 1.6:
                return EmotionResult("happiness", 0.7,
                                     {"happiness": 0.7, "neutral": 0.3}, "heuristic")
            if ratio < 0.85:
                return EmotionResult("sadness", 0.6,
                                     {"sadness": 0.6, "neutral": 0.4}, "heuristic")
            return EmotionResult("neutral", 0.6, {"neutral": 0.6}, "heuristic")
        except Exception:
            return EmotionResult("neutral", 0.5, {"neutral": 1.0}, "heuristic")


_analyzer: Optional[EmotionAnalyzer] = None


def get_emotion_analyzer() -> EmotionAnalyzer:
    global _analyzer
    if _analyzer is None:
        from config import get_settings
        s = get_settings()
        path = f"{s.model_dir}/emotion-ferplus-8.onnx"
        _analyzer = EmotionAnalyzer(model_path=path)
        _analyzer.initialize()
    return _analyzer


def analyze_emotion(face_img: np.ndarray, landmarks: Optional[np.ndarray] = None) -> EmotionResult:
    return get_emotion_analyzer().analyze(face_img, landmarks)
