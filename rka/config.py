"""RKA configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_data_dir() -> Path:
    """Pick the data directory: env var > Docker /data > ~/.rka."""
    import os
    explicit = os.environ.get("RKA_DATA_DIR")
    if explicit:
        return Path(explicit)
    docker_data = Path("/data")
    if docker_data.is_dir():
        return docker_data
    home_data = Path.home() / ".rka"
    home_data.mkdir(parents=True, exist_ok=True)
    return home_data


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
    # Persistent data directory. Houses `rka.db`, `embedding_config.json`,
    # and other persistent state. Tests override via `RKAConfig(data_dir=tmp_path)`.
    # Resolution:
    #   1. RKA_DATA_DIR env var (explicit override)
    #   2. /data (if it exists — Docker volume mount)
    #   3. ~/.rka (Dockerless fallback — created on first use)
    data_dir: Path = Field(
        default_factory=lambda: _resolve_data_dir(),
        description="Persistent data directory",
    )

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

    # Manuscript workbench local suggestion adapter. This is intentionally
    # separate from the legacy general-purpose LLM settings: semantic proposal
    # generation is local-machine-only and never receives a cloud credential.
    workbench_lm_studio_base_url: str = Field(
        default="http://127.0.0.1:1234/v1",
        description="Local-machine OpenAI-compatible LM Studio base URL",
    )
    workbench_lm_studio_model: str = Field(
        default="",
        description="LM Studio model id used for semantic patch suggestions",
    )
    workbench_lm_studio_timeout: int = Field(
        default=120,
        ge=1,
        le=600,
        description="LM Studio proposal request timeout in seconds",
    )

    # Manuscript source synchronization is deliberately opt-in. A
    # manuscript.workspace_ref never grants filesystem authority on its own;
    # it must resolve below one of these os.pathsep-separated roots.
    manuscript_workspace_roots: str = Field(
        default="",
        description=(
            "os.pathsep-separated allowlist of local manuscript workspace roots"
        ),
    )
    manuscript_source_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=20 * 1024 * 1024,
        description="Maximum UTF-8 bytes in one synchronized manuscript source file",
    )

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
