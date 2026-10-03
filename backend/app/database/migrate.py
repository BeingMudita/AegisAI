"""Apply database migrations.

    python -m app.database.migrate            # upgrade DATABASE_URL to the latest schema
    python -m app.database.migrate --seed     # ...then seed users, agents, policies, tools

The Docker image runs this before starting the API when STORAGE_BACKEND=postgres.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AegisAI database migrations.")
    parser.add_argument("--seed", action="store_true", help="seed users, agents, policies, tools")
    args = parser.parse_args()
    upgrade()
    print("Database schema is up to date.")
    if args.seed:
        from app.persistence.seed import seed_reference_data

        seed_reference_data()
        print("Reference data seeded.")


if __name__ == "__main__":
    main()
