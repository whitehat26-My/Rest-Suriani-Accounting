"""Application configuration.

Everything is environment-driven so the same code runs against SQLite (prototype)
or PostgreSQL (production) with no changes.
"""
from __future__ import annotations

import secrets
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

    # ---------------------------------------------------------------- #
    # Authentication
    # ---------------------------------------------------------------- #
    # Signs session cookies and OAuth state. Generated per process if unset,
    # which is fine for local work but logs everyone out on restart - set it
    # explicitly anywhere the app is deployed.
    secret_key: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match the redirect URI registered in the Google Cloud console.
    google_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/callback"

    # Where the browser lands after signing in.
    frontend_url: str = "http://localhost:3000"

    # The shop tablet should not meet a login screen day to day.
    session_days: int = 90
    # Accountant Mode re-locks itself well before the session expires.
    unlock_hours: int = 8

    # Cookies must be Secure in production; local development is plain http.
    cookie_secure: bool = False
    cookie_domain: str | None = None

    # These addresses get OWNER on first sign-in. Everyone else starts as STAFF
    # and has to be promoted, so an unexpected sign-in cannot read the books.
    owner_emails: list[str] = []
    accountant_emails: list[str] = []
    # When set, only these addresses may sign in at all.
    allowed_emails: list[str] = []

    # How many wrong PINs before the gate locks, and for how long.
    pin_max_attempts: int = 5
    pin_lockout_minutes: int = 15

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def auth_enabled(self) -> bool:
        """Auth switches on as soon as Google credentials are present.

        Without them there is no way to sign in at all, so the app would be
        unusable rather than secure. It therefore runs open until it is
        configured, and says so loudly at startup.
        """
        return self.google_configured


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)

if not settings.secret_key:
    # Ephemeral key: signatures stay valid only for the life of this process.
    settings.secret_key = secrets.token_urlsafe(48)
