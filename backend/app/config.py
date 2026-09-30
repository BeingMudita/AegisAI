"""Application configuration loaded from environment variables.

Uses Pydantic settings so every value has a type and a sensible default,
and secrets are read from the (git-ignored) `.env` file.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Phase 1 requires four canonical values — DATABASE_URL, JWT_SECRET,
    MODEL_NAME, ENVIRONMENT — each of which also accepts a legacy alias so
    existing `.env` files keep working.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "AegisAI"
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql+asyncpg://aegis:aegis@localhost:5432/aegisai"

    # Security
    jwt_secret: str = Field(
        default="change-me",
        validation_alias=AliasChoices("JWT_SECRET", "JWT_SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # AI / LLM
    model_name: str = Field(
        default="llama3.1:8b",
        validation_alias=AliasChoices("MODEL_NAME", "OLLAMA_MODEL"),
    )
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout: int = 120
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # RAG
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64
    rag_top_k: int = 5

    # Trust / Firewall / Policies
    trust_threshold: float = 0.6
    firewall_block_threshold: float = 0.8
    policy_config_path: str = "app/policies/default_policies.yaml"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        """True when running in a production environment."""
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
