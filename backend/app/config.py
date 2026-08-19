"""Application configuration.

Everything is environment-driven so the same code runs against SQLite (prototype)
or PostgreSQL (production) with no changes.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Restaurant Accounting System"

    # SQLite for the prototype. Swap for PostgreSQL in production, e.g.
    # DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/restaurant
    database_url: str = f"sqlite:///{BASE_DIR / 'restaurant.db'}"

    # Business identity, shown on the statement headers.
    business_name: str = "Restoran Suriani"
    currency: str = "RM"

    # Financial year start (month, day) - Malaysian SMEs commonly use 1 January.
    fiscal_year_start_month: int = 1
    fiscal_year_start_day: int = 1

    # Where receipt photos are stored.
    upload_dir: Path = BASE_DIR / "uploads"

    # CORS origins for the Next.js frontend.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
