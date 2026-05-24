"""
Détection de stress — signaux combinés sur fenêtre temporelle.

Approche sans capteur biométrique:
    1. Fréquence de clignement (élevée → stress, > 25/min)
    2. Variabilité de pose tête (élevée → agitation)
    3. Asymétrie faciale (le stress accentue les micro-asymétries)
    4. Probabilité d'émotions négatives (anger / fear / sadness / disgust)
       agrégée sur la fenêtre

Sortie: stress_level (low / moderate / high) + score 0..1.

Pour passer en prod sérieuse, ajouter rPPG (reasonable pulse via Eulerian
Video Magnification) pour la variabilité cardiaque.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Optional

import numpy as np
from loguru import logger

from affect.emotion import EmotionResult, get_emotion_analyzer


class StressLevel(str, Enum):
    LOW      = "low"
    MODERATE = "moderate"
    HIGH     = "high"


@dataclass(slots=True)
class StressResult:
    level:                StressLevel
    score:                float                  # 0..1
    blink_rate_per_min:   float
    head_yaw_variance:    float
    negative_emotion_ratio: float
    asymmetry:            float
    n_frames:             int


@dataclass(slots=True)
class _Frame:
    timestamp:   float
    blink:       bool
    yaw:         Optional[float]
    emotion:     str
    asymmetry:   float


# ============================================================
# Analyseur (stateful par session)
# ============================================================

class StressAnalyzer:
    NEGATIVE_EMOTIONS = {"anger", "fear", "sadness", "disgust", "contempt"}

    def __init__(self, window_seconds: float = 30.0):
        self.window_seconds = window_seconds
        self._frames: Deque[_Frame] = deque(maxlen=900)   # ~30s à 30 fps

    def push(
        self,
        face_img: Optional[np.ndarray],
        landmarks: Optional[np.ndarray],
        blink_detected: bool = False,
        head_pose: Optional[tuple[float, float, float]] = None,
        emotion: Optional[EmotionResult] = None,
    ) -> None:
        # Émotion (si non passée, on calcule)
        if emotion is None and face_img is not None:
            try:
                emotion = get_emotion_analyzer().analyze(face_img, landmarks)
            except Exception:
                emotion = None

        asym = self._asymmetry(landmarks) if landmarks is not None else 0.0

        self._frames.append(_Frame(
            timestamp=time.time(),
            blink=blink_detected,
            yaw=head_pose[0] if head_pose else None,
            emotion=(emotion.top_emotion if emotion else "neutral"),
            asymmetry=asym,
        ))
        self._evict_old()

    def _evict_old(self) -> None:
        cutoff = time.time() - self.window_seconds
        while self._frames and self._frames[0].timestamp < cutoff:
            self._frames.popleft()

    def evaluate(self) -> StressResult:
        self._evict_old()
        n = len(self._frames)
        if n < 5:
            return StressResult(StressLevel.LOW, 0.0, 0.0, 0.0, 0.0, 0.0, n)

        # Window real duration (peut être < self.window_seconds si stream récent)
        span = max(1e-3, self._frames[-1].timestamp - self._frames[0].timestamp)
        n_blinks = sum(1 for f in self._frames if f.blink)
        blink_rate = (n_blinks / span) * 60.0     # blinks/minute

        yaws = [f.yaw for f in self._frames if f.yaw is not None]
        yaw_var = float(np.var(yaws)) if yaws else 0.0

        negs = sum(1 for f in self._frames if f.emotion in self.NEGATIVE_EMOTIONS)
        neg_ratio = negs / n

        asyms = [f.asymmetry for f in self._frames]
        asym_mean = float(np.mean(asyms))

        # Score composite (normalisations empiriques)
        blink_norm = float(np.clip((blink_rate - 12.0) / 20.0, 0.0, 1.0))  # 12=base, 32+=très élevé
        yaw_norm   = float(np.clip(yaw_var / 30.0, 0.0, 1.0))
        asym_norm  = float(np.clip(asym_mean / 0.15, 0.0, 1.0))
        score = (0.30 * blink_norm + 0.25 * yaw_norm
                 + 0.30 * neg_ratio + 0.15 * asym_norm)
        score = float(np.clip(score, 0.0, 1.0))

        if score >= 0.65:
            level = StressLevel.HIGH
        elif score >= 0.40:
            level = StressLevel.MODERATE
        else:
            level = StressLevel.LOW

        return StressResult(
            level=level, score=round(score, 3),
            blink_rate_per_min=round(blink_rate, 2),
            head_yaw_variance=round(yaw_var, 3),
            negative_emotion_ratio=round(neg_ratio, 3),
            asymmetry=round(asym_mean, 3),
            n_frames=n,
        )

    @staticmethod
    def _asymmetry(landmarks: np.ndarray) -> float:
        """Mesure d'asymétrie faciale 5pts (oeil_g/d, nez, bouche g/d)."""
        try:
            if len(landmarks) < 5:
                return 0.0
            eye_center  = (landmarks[0] + landmarks[1]) / 2.0
            mouth_center = (landmarks[3] + landmarks[4]) / 2.0
            mid_axis = (eye_center + mouth_center) / 2.0
            # Distance horizontale du nez à l'axe central
            nose = landmarks[2]
            eye_w = float(np.linalg.norm(landmarks[1] - landmarks[0])) + 1e-6
            offset = abs(float(nose[0] - mid_axis[0])) / eye_w
            return float(np.clip(offset, 0.0, 1.0))
        except Exception:
            return 0.0


# ============================================================
# Helpers one-shot (sans state)
# ============================================================

def analyze_stress(frames_data: list[dict]) -> StressResult:
    """
    Analyse un batch de frames déjà annotées.
    Chaque frame: {"blink": bool, "yaw": float, "emotion": str, "asymmetry": float}.
    """
    a = StressAnalyzer()
    now = time.time()
    for i, f in enumerate(frames_data):
        a._frames.append(_Frame(
            timestamp=now - (len(frames_data) - i) * 0.1,
            blink=bool(f.get("blink", False)),
            yaw=f.get("yaw"),
            emotion=f.get("emotion", "neutral"),
            asymmetry=float(f.get("asymmetry", 0.0)),
        ))
    return a.evaluate()
