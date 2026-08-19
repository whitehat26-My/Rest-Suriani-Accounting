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

    # "development" runs conveniently open when unconfigured; "production" refuses
    # to boot unless authentication is fully and safely configured. Set
    # ENVIRONMENT=production on any deployment reachable by other people.
    environment: str = "development"

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
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_partially_configured(self) -> bool:
        """Exactly one of the two Google values set - always an operator mistake."""
        return bool(self.google_client_id) != bool(self.google_client_secret)

    @property
    def auth_enabled(self) -> bool:
        """Whether every request must carry a valid session.

        In production this is always on - the app will not boot without full
        auth configuration (see ``validate_deployment``). In development it turns
        on as soon as Google credentials are present, and otherwise runs open so
        the app is usable on a laptop before it is configured.
        """
        if self.is_production:
            return True
        return self.google_configured

    def validate_deployment(self) -> list[str]:
        """Return a list of fatal misconfigurations. Empty means safe to run.

        This is what turns "someone forgot to set a variable" from a silent
        wide-open deployment into a refusal to start.
        """
        problems: list[str] = []

        # A half-configured Google client is always a mistake, in any
        # environment: the login button would 503 while every gate fell open.
        if self.google_partially_configured:
            problems.append(
                "Exactly one of GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET is set. "
                "Set both, or neither."
            )

        if self.is_production:
            if not self.secret_key or self.secret_key.strip() == "":
                problems.append("SECRET_KEY must be set in production.")
            elif len(self.secret_key) < 32:
                problems.append("SECRET_KEY is too short; use at least 32 characters.")
            if not self.google_configured:
                problems.append(
                    "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in production."
                )
            if not self.owner_emails and not self.allowed_emails:
                # Without this, the first stranger to find the URL becomes owner.
                problems.append(
                    "Set OWNER_EMAILS (and ideally ALLOWED_EMAILS) in production so "
                    "the first sign-in cannot be claimed by an outsider."
                )
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production (HTTPS only).")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not contain '*' with credentials.")

        return problems


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)

if not settings.secret_key:
    if settings.is_production:
        # Never silently mint a per-process key in production: with more than one
        # worker each would sign differently, and a restart would log everyone
        # out. validate_deployment() turns this into a clean startup failure.
        pass
    else:
        # Development convenience: an ephemeral key, valid for this process only.
        settings.secret_key = secrets.token_urlsafe(48)
