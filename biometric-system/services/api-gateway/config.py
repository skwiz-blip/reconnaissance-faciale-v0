"""
Configuration centralisée — chargée depuis .env
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    secret_key: str = "change_me"

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str = ""

    # IA
    face_detection_model: str = "buffalo_l"
    embedding_model: str = "arcface_r100"
    anti_spoof_model: str = "minivision"
    model_dir: str = "./models"
    similarity_threshold: float = 0.6
    liveness_threshold: float = 0.5

    # KYC (Phase 3)
    kyc_face_match_threshold: float = 0.70   # plus strict que reco simple
    ocr_languages: str = "fra+eng"           # syntaxe Tesseract

    # Chiffrement embeddings (Phase 5)
    embedding_encryption_enabled: bool = False
    embedding_encryption_key: str = ""        # hex 64 chars ou base64

    # Métriques (Phase 5)
    metrics_enabled: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 300
    recognition_cache_ttl: int = 30

    # FAISS
    faiss_resync_interval_s: int = 600       # re-sync index depuis Supabase

    # Storage
    storage_bucket: str = "biometric-media"
    max_image_size_mb: int = 5

    # Performance
    gpu_enabled: bool = False
    batch_size: int = 8
    max_faces_per_frame: int = 10
    fps_target: int = 30

    # Sécurité / Auth
    jwt_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 24 * 30   # 30 jours
    api_key_header: str = "X-API-Key"
    rate_limit_per_minute: int = 120

    # CORS — liste séparée par virgules ou * en dev
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.debug or self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("secret_key")
    @classmethod
    def _validate_secret(cls, v: str) -> str:
        if v == "change_me" or len(v) < 32:
            # Avertissement seulement en dev — bloquera l'usage en prod via app_env
            import warnings
            warnings.warn(
                "SECRET_KEY trop faible (< 32 chars) — non utilisable en production",
                stacklevel=2,
            )
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
