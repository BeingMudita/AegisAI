"""Application configuration loaded from environment variables.

Uses Pydantic settings so every value has a type and a sensible default,
and secrets are read from the (git-ignored) `.env` file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load the .env from the repo root regardless of the current working directory,
# so `python -m ...` / uvicorn behave the same whether launched from the repo
# root or from backend/. Prefer backend/.env if one exists, else the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]  # .../AegisAI
_BACKEND_ROOT = Path(__file__).resolve().parents[1]  # .../AegisAI/backend
_ENV_FILE = (
    _BACKEND_ROOT / ".env" if (_BACKEND_ROOT / ".env").exists() else _REPO_ROOT / ".env"
)


class Settings(BaseSettings):
    """Typed application settings.

    Phase 1 requires four canonical values — DATABASE_URL, JWT_SECRET,
    MODEL_NAME, ENVIRONMENT — each of which also accepts a legacy alias so
    existing `.env` files keep working.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
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
    debug: bool = False  # tracebacks in error responses; enable only for local debugging
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql://aegis:aegis@localhost:5432/aegisai"
    # "memory" keeps operational state in-process (development, tests).
    # "postgres" persists events, trust, sessions, tool requests, users, policies
    # and the knowledge base in DATABASE_URL, so several API workers share state.
    storage_backend: str = "memory"  # memory | postgres
    db_pool_size: int = 10
    # A turn's session lock expires after this, so a crashed worker can't hold a
    # session forever.
    session_lease_seconds: int = 300
    # A session with no turn for this long expires and refuses further messages.
    session_idle_minutes: int = 720  # 0 = never

    # Retention (0 = keep forever). A sweeper deletes what is older, once every
    # RETENTION_INTERVAL_MINUTES, on one worker at a time.
    audit_retention_days: int = 90  # security events
    session_retention_days: int = 30  # ended sessions, with their turns
    usage_retention_days: int = 90  # daily budget counters
    retention_interval_minutes: int = 60  # 0 = no background sweeper

    # Security
    jwt_secret: str = Field(
        default="change-me",
        validation_alias=AliasChoices("JWT_SECRET", "JWT_SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Seed accounts for the in-memory user store (development defaults —
    # production refuses to start while any of these are unchanged).
    seed_admin_password: str = "admin123"
    seed_analyst_password: str = "analyst123"
    seed_agent_password: str = "agent123"

    # AI / LLM
    model_name: str = Field(
        default="llama3.1:8b",
        validation_alias=AliasChoices("MODEL_NAME", "OLLAMA_MODEL"),
    )
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout: int = 120
    # auto = use Ollama when reachable, else the deterministic rule-based planner
    llm_backend: str = "auto"  # auto | ollama | rule_based
    agent_max_steps: int = 3
    # Wall-clock budget for one agent turn (seconds). Once it is spent the brain stops
    # calling the LLM and finishes with the deterministic planner, so a turn never
    # outlives the proxy in front of the API (nginx waits 200 s).
    agent_turn_timeout: float = 150.0
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    # auto = sentence-transformers when installed, else a dependency-free hashing embedder
    embedding_backend: str = "auto"  # auto | sentence_transformers | hashing

    # RAG
    # Words per chunk. all-MiniLM-L6-v2 reads at most 256 word-pieces (~190 words) and
    # silently drops the rest, so longer chunks would be only partly embedded.
    rag_chunk_size: int = 180
    rag_chunk_overlap: int = 30
    rag_top_k: int = 5
    rag_seed_corpus: bool = True  # ingest app/rag/seed/ on first use

    # Data ingestion — uploads/, inbox/ and index/ live under data_dir
    # (relative paths are resolved against the backend/ directory).
    data_dir: str = "data"
    max_upload_mb: int = 1024  # per file, for browser uploads
    rag_persist: bool = True  # save the index to data/index/ and reload it on start
    ingest_batch_size: int = 256  # chunks screened + embedded per batch

    # Trust / Firewall / Policies
    trust_threshold: float = 0.6
    firewall_block_threshold: float = 0.8
    firewall_flag_threshold: float = 0.4
    policy_config_path: str = "app/policies/default_policies.yaml"
    # Postgres mode: how long a policy read from the database is reused (seconds).
    policy_cache_seconds: float = 5.0

    # Red-team suites (firewall_cases.yaml, agent_scenarios.yaml); default: ../attack-scenarios
    redteam_suites_dir: str | None = None

    # Human approval: a queued high-risk tool call expires if nobody decides in time.
    approval_ttl_minutes: int = 60

    # Developer platform (SDK / REST gateway / CLI)
    # Optional shared key external apps send as `X-Aegis-Key` to the /v1/secure/*
    # gateway. When unset, the gateway accepts a valid JWT, and is open in a
    # non-production environment so local integration is friction-free.
    aegis_api_key: str | None = None
    # Default path the CLI reads/writes the policy-as-code file from.
    aegis_policy_path: str = "aegis.yaml"
    # Where `aegis inspect` points the browser.
    dashboard_url: str = "http://localhost:5173"

    # Supply chain: a model is used only if it matches its pin in the model manifest.
    # enforce = refuse an unpinned or altered model; warn = use it but record an
    # ANOMALY event; off = no checks. Relative paths resolve against backend/.
    model_provenance: str = "enforce"  # enforce | warn | off
    model_manifest_path: str = "model-manifest.yaml"

    # Telemetry
    audit_buffer_size: int = 5000

    def data_path(self, *parts: str) -> Path:
        """A path under ``data_dir`` (created on demand)."""
        base = Path(self.data_dir)
        if not base.is_absolute():
            base = _BACKEND_ROOT / base
        path = base.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def backend_path(self, path: str) -> Path:
        """``path`` as given if absolute, else resolved against backend/."""
        p = Path(path)
        return p if p.is_absolute() else _BACKEND_ROOT / p

    @property
    def use_postgres(self) -> bool:
        return self.storage_backend.lower() == "postgres"

    @property
    def sync_database_url(self) -> str:
        """DATABASE_URL for the synchronous (psycopg2) driver used by the stores."""
        url = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg2://" + url[len(prefix) :]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg2://" + url[len("postgresql://") :]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        """True when running in a production environment."""
        return self.environment.lower() in {"production", "prod"}

    def insecure_defaults(self) -> list[str]:
        """Names of security settings still at their development defaults."""
        defaults = {
            "JWT_SECRET": (self.jwt_secret, {"change-me", "generate_a_long_random_secret"}),
            "SEED_ADMIN_PASSWORD": (self.seed_admin_password, {"admin123"}),
            "SEED_ANALYST_PASSWORD": (self.seed_analyst_password, {"analyst123"}),
            "SEED_AGENT_PASSWORD": (self.seed_agent_password, {"agent123"}),
        }
        found = [name for name, (value, bad) in defaults.items() if value in bad]
        if len(self.jwt_secret) < 32 and "JWT_SECRET" not in found:
            found.append("JWT_SECRET (shorter than 32 characters)")
        return found


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
