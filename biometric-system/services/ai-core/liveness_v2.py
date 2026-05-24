"""
Liveness Detection v2 — analyse multi-frame + challenge-response.

Étend l'anti_spoof basique en ajoutant:
  1. Analyse de séquence (plusieurs frames sur une fenêtre temporelle)
  2. Challenge-response (l'utilisateur exécute une action: cligner, tourner la tête)
  3. Détection de reflets / glints oculaires (vérifie présence du speculum)
  4. Cohérence de teinte de peau (color moments)
  5. Fréquence Moiré (écran rejoué → patterns réguliers)

Architecture:
  - LivenessV2Detector: analyse instantanée enrichie
  - ChallengeSession: machine à états pour le challenge-response
  - SequenceAnalyzer: agrège plusieurs frames et calcule un score séquentiel
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Optional

import cv2
import numpy as np
from loguru import logger


# ============================================================
# Énums & dataclasses
# ============================================================

class ChallengeAction(str, Enum):
    BLINK       = "blink"
    TURN_LEFT   = "turn_left"
    TURN_RIGHT  = "turn_right"
    LOOK_UP     = "look_up"
    LOOK_DOWN   = "look_down"
    SMILE       = "smile"
    OPEN_MOUTH  = "open_mouth"


class ChallengeStatus(str, Enum):
    PENDING   = "pending"
    PASSED    = "passed"
    FAILED    = "failed"
    EXPIRED   = "expired"


@dataclass(slots=True)
class LivenessV2Result:
    is_live:           bool
    score:             float
    reason:            str
    components:        dict[str, float] = field(default_factory=dict)
    blink_detected:    bool = False
    head_pose:         Optional[tuple[float, float, float]] = None  # yaw, pitch, roll (deg)
    smile_detected:    bool = False
    mouth_open:        bool = False


@dataclass(slots=True)
class ChallengeAttempt:
    challenge_id:  str
    action:        ChallengeAction
    status:        ChallengeStatus
    progress:      float          # 0..1
    expires_at:    float
    started_at:    float
    metadata:      dict = field(default_factory=dict)


# ============================================================
# Détecteur v2 — analyse d'une frame
# ============================================================

class LivenessV2Detector:
    """
    Analyseur de liveness avancé sur une frame unique.
    Pour l'analyse multi-frame, voir SequenceAnalyzer.
    """

    EAR_BLINK_THRESHOLD = 0.21
    MOUTH_OPEN_THRESHOLD = 0.45
    SMILE_RATIO_THRESHOLD = 1.6

    def __init__(self, threshold: float = 0.55):
        self.threshold = threshold

    def analyze(
        self,
        face_img: np.ndarray,
        landmarks: Optional[np.ndarray] = None,
    ) -> LivenessV2Result:
        if face_img is None or face_img.size == 0:
            return LivenessV2Result(False, 0.0, "Image vide")

        components: dict[str, float] = {}

        # 1. Texture LBP (locales binaires)
        components["texture_lbp"] = self._texture_lbp(face_img)

        # 2. Cohérence de couleur (peau réelle vs photo)
        components["color_consistency"] = self._color_consistency(face_img)

        # 3. Détection de Moiré (écran rejoué)
        components["moire"] = self._moire_pattern_score(face_img)

        # 4. Glints oculaires (reflets)
        components["eye_glints"] = self._eye_glints_score(face_img, landmarks)

        # 5. Géométrie faciale (head pose + EAR + MAR)
        blink, head_pose, smile, mouth_open = False, None, False, False
        if landmarks is not None and len(landmarks) >= 5:
            blink, ear = self._ear_from_landmarks(landmarks)
            components["eye_aspect_ratio"] = ear
            head_pose = self._estimate_head_pose(landmarks, face_img.shape)
            smile, smile_ratio = self._smile_score(landmarks)
            mouth_open, mar = self._mouth_open_score(landmarks)
            components["smile_ratio"] = smile_ratio
            components["mouth_aspect_ratio"] = mar

        # Score final pondéré
        weights = {
            "texture_lbp":         0.30,
            "color_consistency":   0.15,
            "moire":               0.20,
            "eye_glints":          0.15,
            "eye_aspect_ratio":    0.10,
            "smile_ratio":         0.05,
            "mouth_aspect_ratio":  0.05,
        }
        total_w = 0.0
        score = 0.0
        for k, v in components.items():
            w = weights.get(k, 0.0)
            if w > 0:
                # eye_aspect_ratio → on transforme en score (clignement = bonus)
                comp = v
                if k == "eye_aspect_ratio":
                    comp = min(1.0, v / 0.3)
                elif k in ("smile_ratio", "mouth_aspect_ratio"):
                    comp = min(1.0, v)
                score += w * comp
                total_w += w
        final = score / total_w if total_w > 0 else 0.5

        return LivenessV2Result(
            is_live=final >= self.threshold,
            score=round(float(final), 3),
            reason=" | ".join(f"{k}={v:.2f}" for k, v in components.items()),
            components={k: round(float(v), 3) for k, v in components.items()},
            blink_detected=blink,
            head_pose=head_pose,
            smile_detected=smile,
            mouth_open=mouth_open,
        )

    # ----------------- composantes -----------------

    def _texture_lbp(self, face_img: np.ndarray) -> float:
        """Vraie LBP (3x3 voisins). Une vraie peau a une distribution riche d'uniformité."""
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (96, 96))
        h, w = gray.shape
        lbp = np.zeros((h - 2, w - 2), dtype=np.uint8)
        center = gray[1:-1, 1:-1]
        offsets = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, 1),  (1, 1),  (1, 0),
            (1, -1), (0, -1),
        ]
        for i, (dy, dx) in enumerate(offsets):
            shifted = gray[1+dy:h-1+dy, 1+dx:w-1+dx]
            lbp |= ((shifted >= center).astype(np.uint8) << i)

        # Histogramme normalisé → entropie
        hist = np.bincount(lbp.ravel(), minlength=256).astype(np.float32)
        hist /= max(1.0, hist.sum())
        # entropie de Shannon
        entropy = -float(np.sum(hist[hist > 0] * np.log2(hist[hist > 0])))
        # entropie typique: photo ~5.5, vraie peau ~7.0-7.5
        return float(np.clip((entropy - 5.0) / 2.5, 0.0, 1.0))

    def _color_consistency(self, face_img: np.ndarray) -> float:
        """Vraie peau: histogramme HSV concentré. Photo imprimée: dispersé."""
        hsv = cv2.cvtColor(face_img, cv2.COLOR_BGR2HSV)
        h, s = hsv[..., 0], hsv[..., 1]
        # Variance de teinte dans la zone centrale (visage)
        cy, cx = face_img.shape[0] // 2, face_img.shape[1] // 2
        win = face_img.shape[0] // 4
        roi_h = h[cy-win:cy+win, cx-win:cx+win]
        if roi_h.size == 0:
            return 0.5
        hue_std = float(np.std(roi_h))
        sat_mean = float(np.mean(s))
        # Faible variance hue + saturation moyenne = peau réelle
        score = (1.0 - min(1.0, hue_std / 25.0)) * 0.6 + min(1.0, sat_mean / 80.0) * 0.4
        return float(np.clip(score, 0.0, 1.0))

    def _moire_pattern_score(self, face_img: np.ndarray) -> float:
        """
        Détection des motifs Moiré (écran rejoué).
        Bas score = Moiré détecté = probablement écran. On retourne 1 - moiré.
        """
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (128, 128))
        f = np.fft.fft2(gray)
        fshift = np.fft.fftshift(f)
        spectrum = np.log1p(np.abs(fshift))
        # Bande de fréquences moyennes — Moiré s'y concentre
        h, w = spectrum.shape
        cy, cx = h // 2, w // 2
        mask = np.zeros_like(spectrum)
        cv2.circle(mask, (cx, cy), 35, 1, -1)
        cv2.circle(mask, (cx, cy), 12, 0, -1)
        mid_band = spectrum * mask
        # Variance dans cette bande
        var = float(np.var(mid_band[mid_band > 0])) if np.any(mid_band > 0) else 0.0
        # Plus la variance est élevée, plus on suspecte un Moiré
        moire = float(np.clip(var / 4.0, 0.0, 1.0))
        return 1.0 - moire

    def _eye_glints_score(
        self, face_img: np.ndarray, landmarks: Optional[np.ndarray]
    ) -> float:
        """Cherche les reflets blancs dans les yeux — signe de vivacité."""
        if landmarks is None or len(landmarks) < 2:
            return 0.5

        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        found = 0
        for eye in landmarks[:2]:
            ex, ey = int(eye[0]), int(eye[1])
            # ROI petit autour de l'œil
            r = max(4, int(min(H, W) * 0.04))
            y1, y2 = max(0, ey - r), min(H, ey + r)
            x1, x2 = max(0, ex - r), min(W, ex + r)
            roi = gray[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            # Glint = pixel très brillant entouré de sombre
            max_val = int(np.max(roi))
            min_val = int(np.min(roi))
            if max_val - min_val > 80 and max_val > 200:
                found += 1
        return min(1.0, found / 2.0 * 0.5 + 0.5)  # 0.5 baseline, max 1.0

    def _ear_from_landmarks(self, landmarks: np.ndarray) -> tuple[bool, float]:
        """Estimation EAR (Eye Aspect Ratio) avec 5pts InsightFace."""
        try:
            left, right = landmarks[0], landmarks[1]
            inter = float(np.linalg.norm(right - left))
            if len(landmarks) >= 5:
                mouth_w = float(np.linalg.norm(landmarks[3] - landmarks[4]) + 1e-6)
                ear = inter / mouth_w * 0.3
            else:
                ear = 0.3
            return ear < self.EAR_BLINK_THRESHOLD, ear
        except Exception:
            return False, 0.3

    def _estimate_head_pose(
        self, landmarks: np.ndarray, shape: tuple
    ) -> Optional[tuple[float, float, float]]:
        """Pose approximée yaw/pitch/roll à partir des 5pts faciaux."""
        try:
            left_eye = landmarks[0]
            right_eye = landmarks[1]
            nose = landmarks[2] if len(landmarks) > 2 else None
            if nose is None:
                return None
            eye_center = (left_eye + right_eye) / 2.0
            dx = right_eye[0] - left_eye[0]
            dy = right_eye[1] - left_eye[1]
            roll = float(np.degrees(np.arctan2(dy, dx)))
            # Yaw approximé par décentrage du nez
            nose_dx = nose[0] - eye_center[0]
            eye_dist = float(np.linalg.norm(right_eye - left_eye)) + 1e-6
            yaw = float(np.clip(nose_dx / eye_dist * 60.0, -60.0, 60.0))
            # Pitch approximé par hauteur du nez vs yeux
            pitch = float((nose[1] - eye_center[1]) / eye_dist * 30.0)
            return (yaw, pitch, roll)
        except Exception:
            return None

    def _smile_score(self, landmarks: np.ndarray) -> tuple[bool, float]:
        try:
            if len(landmarks) < 5:
                return False, 0.0
            mouth_l, mouth_r = landmarks[3], landmarks[4]
            mouth_w = float(np.linalg.norm(mouth_r - mouth_l))
            eye_w = float(np.linalg.norm(landmarks[1] - landmarks[0])) + 1e-6
            ratio = mouth_w / eye_w
            return ratio > self.SMILE_RATIO_THRESHOLD, ratio
        except Exception:
            return False, 0.0

    def _mouth_open_score(self, landmarks: np.ndarray) -> tuple[bool, float]:
        # Avec 5pts, on n'a pas de hauteur de bouche réelle.
        # Heuristique très grossière: signaler "ouvert" si le centre de bouche
        # est anormalement loin de l'axe œil.
        try:
            if len(landmarks) < 5:
                return False, 0.0
            mouth_center = (landmarks[3] + landmarks[4]) / 2.0
            eye_center = (landmarks[0] + landmarks[1]) / 2.0
            dist = float(np.linalg.norm(mouth_center - eye_center))
            eye_w = float(np.linalg.norm(landmarks[1] - landmarks[0])) + 1e-6
            mar = dist / eye_w / 4.0  # normalisation empirique
            return mar > self.MOUTH_OPEN_THRESHOLD, mar
        except Exception:
            return False, 0.0


# ============================================================
# Analyseur de séquence
# ============================================================

class SequenceAnalyzer:
    """
    Agrège les résultats sur N frames pour décider de la liveness:
    - Variance de pose nécessaire (un visage figé est suspect)
    - Au moins un clignement attendu sur la fenêtre
    - Score moyen au-dessus du seuil
    """

    def __init__(self, window_seconds: float = 3.0, min_score: float = 0.55):
        self.window_seconds = window_seconds
        self.min_score = min_score
        self._history: Deque[tuple[float, LivenessV2Result]] = deque(maxlen=200)

    def push(self, result: LivenessV2Result) -> None:
        self._history.append((time.time(), result))
        self._evict_old()

    def _evict_old(self) -> None:
        cutoff = time.time() - self.window_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def verdict(self) -> dict:
        self._evict_old()
        n = len(self._history)
        if n < 5:
            return {"ready": False, "n_frames": n}

        scores = [r.score for _, r in self._history]
        blinks = sum(1 for _, r in self._history if r.blink_detected)

        # Variance pose (yaw)
        yaws = [r.head_pose[0] for _, r in self._history if r.head_pose]
        yaw_var = float(np.var(yaws)) if yaws else 0.0

        mean_score = float(np.mean(scores))
        min_score_ok = mean_score >= self.min_score
        has_blink = blinks >= 1
        has_motion = yaw_var >= 1.5   # variance > ~1.2° de tête bouge

        is_live = min_score_ok and (has_blink or has_motion)

        return {
            "ready":       True,
            "n_frames":    n,
            "mean_score":  round(mean_score, 3),
            "blinks":      blinks,
            "yaw_variance": round(yaw_var, 3),
            "is_live":     is_live,
            "reasons": {
                "score_ok":  min_score_ok,
                "has_blink": has_blink,
                "has_motion": has_motion,
            },
        }


# ============================================================
# Challenge / Response
# ============================================================

class ChallengeEvaluator:
    """
    Reçoit successivement des frames + landmarks et évalue si l'action
    demandée a été réalisée (clignement, rotation tête, sourire, etc.).
    """

    EXPIRY_SECONDS = 15.0
    YAW_TURN_DEG = 18.0
    PITCH_DEG = 12.0

    def __init__(self, detector: LivenessV2Detector):
        self.detector = detector
        self._sessions: dict[str, ChallengeAttempt] = {}

    def issue(self, action: Optional[ChallengeAction] = None) -> ChallengeAttempt:
        if action is None:
            action = random.choice(list(ChallengeAction))
        import uuid
        attempt = ChallengeAttempt(
            challenge_id=uuid.uuid4().hex,
            action=action,
            status=ChallengeStatus.PENDING,
            progress=0.0,
            expires_at=time.time() + self.EXPIRY_SECONDS,
            started_at=time.time(),
            metadata={"frames_seen": 0},
        )
        self._sessions[attempt.challenge_id] = attempt
        return attempt

    def get(self, challenge_id: str) -> Optional[ChallengeAttempt]:
        return self._sessions.get(challenge_id)

    def submit_frame(
        self,
        challenge_id: str,
        face_img: np.ndarray,
        landmarks: Optional[np.ndarray],
    ) -> ChallengeAttempt:
        attempt = self._sessions.get(challenge_id)
        if attempt is None:
            raise ValueError("Challenge introuvable")
        if time.time() > attempt.expires_at and attempt.status == ChallengeStatus.PENDING:
            attempt.status = ChallengeStatus.EXPIRED
            return attempt
        if attempt.status != ChallengeStatus.PENDING:
            return attempt

        analysis = self.detector.analyze(face_img, landmarks)
        attempt.metadata["frames_seen"] += 1

        passed, progress = self._check_action(attempt.action, analysis, attempt.metadata)
        attempt.progress = max(attempt.progress, progress)
        if passed:
            attempt.status = ChallengeStatus.PASSED
            attempt.progress = 1.0
            attempt.metadata["completed_at"] = time.time()
        elif attempt.metadata["frames_seen"] > 90 and attempt.progress < 0.3:
            attempt.status = ChallengeStatus.FAILED
        return attempt

    def _check_action(
        self,
        action: ChallengeAction,
        analysis: LivenessV2Result,
        meta: dict,
    ) -> tuple[bool, float]:
        if action == ChallengeAction.BLINK:
            blinks = meta.get("blinks", 0)
            if analysis.blink_detected:
                blinks += 1
            meta["blinks"] = blinks
            return blinks >= 1, min(1.0, blinks)

        if analysis.head_pose is None:
            return False, 0.0
        yaw, pitch, _ = analysis.head_pose

        if action == ChallengeAction.TURN_LEFT:
            return yaw < -self.YAW_TURN_DEG, min(1.0, max(0.0, -yaw / self.YAW_TURN_DEG))
        if action == ChallengeAction.TURN_RIGHT:
            return yaw > self.YAW_TURN_DEG, min(1.0, max(0.0, yaw / self.YAW_TURN_DEG))
        if action == ChallengeAction.LOOK_UP:
            return pitch < -self.PITCH_DEG, min(1.0, max(0.0, -pitch / self.PITCH_DEG))
        if action == ChallengeAction.LOOK_DOWN:
            return pitch > self.PITCH_DEG, min(1.0, max(0.0, pitch / self.PITCH_DEG))
        if action == ChallengeAction.SMILE:
            return analysis.smile_detected, 1.0 if analysis.smile_detected else 0.3
        if action == ChallengeAction.OPEN_MOUTH:
            return analysis.mouth_open, 1.0 if analysis.mouth_open else 0.3
        return False, 0.0

    def cleanup_expired(self) -> int:
        now = time.time()
        expired = [k for k, a in self._sessions.items()
                   if now - a.started_at > self.EXPIRY_SECONDS * 4]
        for k in expired:
            self._sessions.pop(k, None)
        return len(expired)


# ============================================================
# Singletons
# ============================================================

_detector_v2: Optional[LivenessV2Detector] = None
_challenger: Optional[ChallengeEvaluator] = None


def get_liveness_v2() -> LivenessV2Detector:
    global _detector_v2
    if _detector_v2 is None:
        from config import get_settings
        s = get_settings()
        _detector_v2 = LivenessV2Detector(threshold=s.liveness_threshold)
    return _detector_v2


def get_challenger() -> ChallengeEvaluator:
    global _challenger
    if _challenger is None:
        _challenger = ChallengeEvaluator(get_liveness_v2())
    return _challenger
