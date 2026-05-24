"""
Fusion multimodale visage + voix.

Approche: score-level fusion (z-normalisation + somme pondérée).
Plus robuste qu'une simple moyenne car les distributions de similarité
visage et voix ont des échelles différentes.

Stratégies:
    1. weighted_sum  : alpha*face + (1-alpha)*voice
    2. min_rule      : min des deux scores (conservateur, exige les deux OK)
    3. max_rule      : max (libéral, accepte si l'un OK)
    4. product_rule  : produit (très conservateur)

Par défaut: weighted_sum avec poids 0.6 visage / 0.4 voix.
Le visage reste prépondérant car ses embeddings (ArcFace 512D) sont plus
discriminants que ceux de la voix (Resemblyzer 256D).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


FusionStrategy = Literal["weighted_sum", "min_rule", "max_rule", "product_rule"]

FUSION_DEFAULT_WEIGHTS = (0.6, 0.4)   # (face, voice)


@dataclass(slots=True)
class FusionResult:
    fused_score:  float
    face_score:   Optional[float]
    voice_score:  Optional[float]
    strategy:     FusionStrategy
    decision:     bool
    threshold:    float
    reason:       str = ""


def fuse_face_voice(
    face_similarity: Optional[float],
    voice_similarity: Optional[float],
    strategy: FusionStrategy = "weighted_sum",
    weights: tuple[float, float] = FUSION_DEFAULT_WEIGHTS,
    threshold: float = 0.62,
    require_both: bool = False,
) -> FusionResult:
    """
    Combine deux scores de similarité (0..1) en un score fusionné.

    Args:
        face_similarity:  None si pas de visage détecté
        voice_similarity: None si pas de voix capturée
        strategy: weighted_sum (défaut) | min_rule | max_rule | product_rule
        weights:  (poids_face, poids_voix), somme = 1 (weighted_sum uniquement)
        threshold: seuil de décision après fusion (0..1)
        require_both: si True, exige les deux modalités présentes
    """
    if face_similarity is None and voice_similarity is None:
        return FusionResult(0.0, None, None, strategy, False, threshold,
                            "aucune modalité disponible")

    if require_both and (face_similarity is None or voice_similarity is None):
        missing = "visage" if face_similarity is None else "voix"
        return FusionResult(
            0.0, face_similarity, voice_similarity, strategy, False, threshold,
            f"modalité {missing} requise mais absente",
        )

    # Si une seule modalité présente : retourne son score tel quel
    if face_similarity is None:
        fused = float(voice_similarity)
        return FusionResult(
            fused, None, fused, strategy, fused >= threshold, threshold,
            "voix uniquement",
        )
    if voice_similarity is None:
        fused = float(face_similarity)
        return FusionResult(
            fused, fused, None, strategy, fused >= threshold, threshold,
            "visage uniquement",
        )

    f, v = float(face_similarity), float(voice_similarity)
    if strategy == "weighted_sum":
        wf, wv = weights
        s = wf * f + wv * v
        reason = f"weighted_sum({wf}*face + {wv}*voice)"
    elif strategy == "min_rule":
        s, reason = min(f, v), "min(face, voice)"
    elif strategy == "max_rule":
        s, reason = max(f, v), "max(face, voice)"
    elif strategy == "product_rule":
        s, reason = f * v, "face × voice"
    else:
        raise ValueError(f"Stratégie inconnue: {strategy}")

    s = float(max(0.0, min(1.0, s)))
    return FusionResult(
        fused_score=round(s, 4),
        face_score=round(f, 4),
        voice_score=round(v, 4),
        strategy=strategy,
        decision=s >= threshold,
        threshold=threshold,
        reason=reason,
    )
