"""RKA configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RKAConfig(BaseSettings):
    """Configuration loaded from .env / environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="RKA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Project
    project_dir: Path = Field(default=Path("."), description="Project root directory")
    db_path: Path = Field(default=Path("rka.db"), description="SQLite database path")
    # Volume mount that survives `docker compose up -d --build`. Houses
    # `rka.db`, `embedding_config.json`, and other persistent state.
    # Tests override via `RKAConfig(data_dir=tmp_path)`.
    data_dir: Path = Field(default=Path("/data"), description="Persistent data directory")

    # Server
    host: str = Field(default="127.0.0.1", description="API server host")
    port: int = Field(default=9712, description="API server port")

    # LLM — configured at runtime from Settings page or env vars.
    llm_model: str = Field(default="", description="LiteLLM model identifier")
    llm_api_base: str | None = Field(default=None, description="LLM API base URL")
    llm_api_key: str | None = Field(default=None, description="Optional API key")
    llm_enabled: bool = Field(default=True, description="Enable LLM features")
    llm_think: bool = Field(
        default=False,
        description="Enable thinking mode for reasoning models (disable for structured extraction)",
    )

    # LLM context window — auto-detected from backend, or set manually
    llm_context_window: int = Field(default=0, description="Model context window in tokens (0 = unknown/auto)")
    llm_request_timeout: int = Field(default=120, description="Timeout for LLM requests in seconds")

    # Embeddings — v2.4.0 (Mission D) flips the default to ON. Persistent
    # backend config lives at /data/embedding_config.json; this env var
    # remains the master enable/disable switch for the in-process
    # EmbeddingService.
    embedding_model: str = Field(
        default="nomic-ai/nomic-embed-text-v1.5", description="FastEmbed model"
    )
    embeddings_enabled: bool = Field(default=True, description="Enable embedding generation")

    # Context Engine — v2.4 (dec_01KQQPD6Y6B362T3K08368BDMP) removed temperature
    # bucketing and token-budget arithmetic. Ranking is SQL-time importance ×
    # centrality × recency. The former env vars (RKA_CONTEXT_HOT_DAYS,
    # RKA_CONTEXT_WARM_DAYS, RKA_CONTEXT_DEFAULT_MAX_TOKENS) were removed.

    # Background jobs
    job_poll_interval: float = Field(default=1.0, description="Worker poll interval in seconds")
    job_lease_seconds: int = Field(default=300, description="Job lease duration before recovery")
    job_max_attempts: int = Field(default=5, description="Max attempts before a job is marked failed")

    @property
    def database_url(self) -> str:
        """Resolve database path relative to project dir."""
        db = self.db_path
        if not db.is_absolute():
            db = self.project_dir / db
        return str(db)
