"""Analyse affective: émotions, stress, micro-expressions."""
from affect.emotion import (
    EmotionResult, EmotionAnalyzer, analyze_emotion, EMOTION_LABELS,
)
from affect.stress import (
    StressResult, StressAnalyzer, analyze_stress,
)

__all__ = [
    "EmotionResult", "EmotionAnalyzer", "analyze_emotion", "EMOTION_LABELS",
    "StressResult", "StressAnalyzer", "analyze_stress",
]
