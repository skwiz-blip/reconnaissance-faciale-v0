"""
GPU runtime utilities — détection, batch inference, warmup, monitoring.

Stratégie:
    1. Détection auto (CUDA → TensorRT → CoreML → CPU)
    2. Batch inference pour ArcFace (gain 3-5× sur GPU)
    3. Warmup à la première utilisation (compile kernels)
    4. Monitoring temps inference + débit
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from loguru import logger


@dataclass(slots=True)
class GPUInfo:
    available:    bool
    provider:     str            # "CUDA" | "TensorRT" | "CoreML" | "CPU"
    device_name:  str = ""
    memory_mb:    int = 0


@dataclass(slots=True)
class InferenceMetrics:
    total_calls:  int = 0
    total_ms:     float = 0.0
    last_batch:   int = 0
    last_ms:      float = 0.0
    warmup_done:  bool = False

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.total_calls if self.total_calls else 0.0

    @property
    def throughput_per_sec(self) -> float:
        return (self.total_calls * 1000.0 / self.total_ms) if self.total_ms else 0.0


# ============================================================
# Détection GPU
# ============================================================

def detect_gpu() -> GPUInfo:
    """Détecte le meilleur runtime disponible — ne charge rien."""
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except ImportError:
        return GPUInfo(available=False, provider="CPU",
                       device_name="onnxruntime non installé")

    # Priorité: TensorRT > CUDA > CoreML > CPU
    if "TensorrtExecutionProvider" in available:
        return GPUInfo(True, "TensorRT", *_cuda_device_info())
    if "CUDAExecutionProvider" in available:
        return GPUInfo(True, "CUDA", *_cuda_device_info())
    if "CoreMLExecutionProvider" in available:
        return GPUInfo(True, "CoreML", "Apple Silicon", 0)
    return GPUInfo(False, "CPU", "Aucun GPU détecté", 0)


def _cuda_device_info() -> tuple[str, int]:
    """Retourne (nom_device, mémoire_mb) via pynvml si disponible."""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode()
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return name, mem.total // (1024 * 1024)
    except Exception:
        return "GPU CUDA", 0


def providers_for(gpu_enabled: bool) -> list[str]:
    """Retourne la liste ordonnée des providers ONNX Runtime."""
    if not gpu_enabled:
        return ["CPUExecutionProvider"]
    info = detect_gpu()
    if info.provider == "TensorRT":
        return ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    if info.provider == "CUDA":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if info.provider == "CoreML":
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


# ============================================================
# Métriques globales
# ============================================================

_metrics = InferenceMetrics()


def get_metrics() -> InferenceMetrics:
    return _metrics


def record_inference(batch_size: int, elapsed_ms: float) -> None:
    _metrics.total_calls += batch_size
    _metrics.total_ms += elapsed_ms
    _metrics.last_batch = batch_size
    _metrics.last_ms = elapsed_ms


def mark_warmup_done() -> None:
    _metrics.warmup_done = True


# ============================================================
# Preprocessing batch ArcFace
# ============================================================

def preprocess_arcface_batch(faces: list[np.ndarray]) -> np.ndarray:
    """
    Transforme une liste d'images BGR en tensor (N, 3, 112, 112) prêt pour ArcFace.
    Beaucoup plus rapide en batch (1 cudaMemcpy au lieu de N).
    """
    import cv2
    out = np.zeros((len(faces), 3, 112, 112), dtype=np.float32)
    for i, face in enumerate(faces):
        if face.shape[:2] != (112, 112):
            face = cv2.resize(face, (112, 112))
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32)
        rgb = (rgb - 127.5) / 128.0
        out[i] = rgb.transpose(2, 0, 1)
    return out
