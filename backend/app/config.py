"""Application settings loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # .env is read from the backend folder regardless of the working directory (PM2, IDE, tests).
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Aviation Intelligence RAG"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    log_file: str | None = None  # e.g. logs/app.log -> rotating file (5 MB x 3) instead of stdout

    # --- Auth between the Next.js proxy and this API ---
    backend_api_key: str = Field(default="", description="Required on every request except /api/health")
    backend_admin_key: str = Field(default="", description="Required for upload/delete endpoints")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Supabase ---
    database_url: str = ""  # Supavisor pooler URL (session mode recommended)
    db_pool_min: int = 1
    db_pool_max: int = 5
    supabase_url: str = ""  # https://<ref>.supabase.co
    supabase_service_role_key: str = ""
    supabase_bucket: str = "documents"

    # --- Embeddings (local, CPU) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_batch_size: int = 16
    embedding_threads: int = 2
    embedding_cache_dir: str | None = ".cache/fastembed"  # persistent; the default temp dir may be wiped
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "

    # --- LLM (Groq) ---
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048  # includes reasoning tokens for reasoning models
    llm_reasoning_effort: str = "low"  # for reasoning models (gpt-oss); set empty for others
    # Tried in order when the primary model is rate-limited (each Groq model has its own free quota).
    groq_fallback_models: list[str] = Field(default_factory=lambda: ["openai/gpt-oss-20b"])
    llm_timeout_s: float = 60.0

    # --- Retrieval ---
    retrieval_candidates: int = 20
    retrieval_top_k: int = 5  # passages sent to the LLM (fewer tokens = more answers within Groq limits)
    min_relevance: float = 0.45

    # --- Chunking ---
    chunk_size_chars: int = 1100
    chunk_overlap_chars: int = 200

    # --- Upload limits ---
    max_upload_mb: int = 25
    max_pages: int = 500

    # --- Rate limits (slowapi syntax) ---
    chat_rate_limit: str = "10/minute;200/day"

    @field_validator("embedding_cache_dir", "log_file")
    @classmethod
    def resolve_cache_dir(cls, v: str | None) -> str | None:
        # Relative paths are relative to the backend folder, not the process working directory.
        if v and not Path(v).is_absolute():
            return str(BACKEND_DIR / v)
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
