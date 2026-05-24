"""
Génération d'embeddings faciaux — ArcFace 512D via ONNX Runtime
Normalise les vecteurs pour comparaison cosinus.
"""
import numpy as np
import cv2
from pathlib import Path
from typing import Optional
from loguru import logger

try:
    import onnxruntime as ort
    ONNX_OK = True
except ImportError:
    ONNX_OK = False
    logger.warning("ONNX Runtime non disponible")

try:
    import insightface
    INSIGHTFACE_OK = True
except ImportError:
    INSIGHTFACE_OK = False


EMBEDDING_DIM = 512
INPUT_SIZE = (112, 112)   # ArcFace standard


class FaceEmbedder:
    """
    Génère des embeddings 512D à partir d'une image de visage aligné.
    Utilise ArcFace (InsightFace) ou ONNX Runtime directement.
    Supports batch inference (gain 3-5× sur GPU).
    """

    def __init__(self,
                 model_path: Optional[str] = None,
                 gpu: bool = False):
        self.model_path = model_path
        self.gpu = gpu
        self._session = None
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True

        from gpu_runtime import providers_for, detect_gpu
        providers = providers_for(self.gpu)
        info = detect_gpu()
        if self.gpu:
            logger.info(f"GPU detection: {info.provider} | {info.device_name} | {info.memory_mb}MB")

        # Chercher le modèle ONNX local
        if self.model_path and Path(self.model_path).exists() and ONNX_OK:
            try:
                so = ort.SessionOptions()
                so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                so.intra_op_num_threads = 0  # auto
                self._session = ort.InferenceSession(
                    self.model_path, sess_options=so, providers=providers
                )
                self._initialized = True
                logger.success(
                    f"Embedder ONNX chargé: {self.model_path} "
                    f"(providers={self._session.get_providers()})"
                )
                self.warmup()
                return True
            except Exception as e:
                logger.error(f"ONNX load échoué: {e}")

        # InsightFace gère directement l'embedding (via detector)
        # Dans ce cas l'embedding est déjà dans DetectedFace.embedding
        self._initialized = True
        logger.info("Embedder: utilise InsightFace natif (via FaceAnalysis)")
        return True

    def warmup(self, batch_size: int = 4) -> None:
        """Lance une inférence factice pour compiler les kernels GPU."""
        if self._session is None:
            return
        try:
            from gpu_runtime import mark_warmup_done
            dummy = np.zeros((batch_size, 3, 112, 112), dtype=np.float32)
            name = self._session.get_inputs()[0].name
            for _ in range(2):
                self._session.run(None, {name: dummy})
            mark_warmup_done()
            logger.info(f"Warmup embedder OK (batch={batch_size})")
        except Exception as e:
            logger.warning(f"Warmup échoué: {e}")

    def embed(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        """
        Génère un vecteur 512D normalisé à partir d'un crop de visage.

        Args:
            face_img: Image BGR du visage (n'importe quelle taille)

        Returns:
            np.ndarray shape (512,) normalisé L2, ou None si erreur
        """
        if not self._initialized:
            self.initialize()

        if face_img is None or face_img.size == 0:
            return None

        try:
            if self._session is not None:
                return self._embed_onnx(face_img)
            # Fallback: retourne embedding aléatoire normalisé (dev only)
            logger.warning("Pas de modèle ONNX — embedding simulé (dev mode)")
            return self._mock_embedding()
        except Exception as e:
            logger.error(f"Erreur embedding: {e}")
            return None

    def _embed_onnx(self, face_img: np.ndarray) -> np.ndarray:
        """Inférence ONNX simple frame (cas non-batché)."""
        embeddings = self.embed_batch([face_img])
        return embeddings[0] if embeddings else None

    def embed_batch(self, face_imgs: list[np.ndarray]) -> list[np.ndarray]:
        """
        Inférence batch ArcFace — gain 3-5× sur GPU pour N>=4.
        Retourne N embeddings normalisés L2.
        """
        if not face_imgs:
            return []
        if not self._initialized:
            self.initialize()
        if self._session is None:
            # Fallback mock (dev)
            return [self._mock_embedding() for _ in face_imgs]

        import time as _time
        from gpu_runtime import preprocess_arcface_batch, record_inference

        batch = preprocess_arcface_batch(face_imgs)
        input_name = self._session.get_inputs()[0].name

        t0 = _time.perf_counter()
        output = self._session.run(None, {input_name: batch})[0]
        elapsed = (_time.perf_counter() - t0) * 1000.0
        record_inference(len(face_imgs), elapsed)

        return [self.normalize(emb) for emb in output]

    @staticmethod
    def normalize(embedding: np.ndarray) -> np.ndarray:
        """Normalisation L2 pour comparaison cosinus"""
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return embedding
        return embedding / norm

    @staticmethod
    def _mock_embedding() -> np.ndarray:
        """Embedding aléatoire normalisé — dev/test uniquement"""
        emb = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        return emb / np.linalg.norm(emb)

    @staticmethod
    def cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Similarité cosinus entre deux embeddings normalisés"""
        return float(np.dot(emb1, emb2))

    @staticmethod
    def euclidean_distance(emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Distance euclidienne entre deux embeddings"""
        return float(np.linalg.norm(emb1 - emb2))


# Singleton
_embedder: Optional[FaceEmbedder] = None


def get_embedder() -> FaceEmbedder:
    global _embedder
    if _embedder is None:
        from config import get_settings
        s = get_settings()
        model_path = f"{s.model_dir}/arcface_r100.onnx"
        _embedder = FaceEmbedder(model_path=model_path, gpu=s.gpu_enabled)
        _embedder.initialize()
    return _embedder
