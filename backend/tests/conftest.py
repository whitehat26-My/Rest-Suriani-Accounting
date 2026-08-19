"""Test fixtures.

The database URL is set before any application module is imported, so the tests
run against a throwaway SQLite file and never touch a real database.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="restaurant-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_TMP_DIR / "uploads")

# Environment variables beat the .env file, so this pins the test suite to a
# known auth state regardless of whether the developer running it happens to
# have Google credentials configured locally. Tests that want authentication
# switch it on themselves through the `auth_on` fixture.
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["SECRET_KEY"] = "test-only-signing-key"

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.seed import ensure_chart_of_accounts  # noqa: E402


@pytest.fixture()
def db() -> Iterator:
    """A clean database with the chart of accounts loaded, per test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_chart_of_accounts()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db) -> Iterator:
    """A FastAPI test client sharing the same clean database."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def _get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_on(monkeypatch):
    """Turn authentication on, as configuring Google credentials would.

    Shared by the auth and security suites so both can exercise the gates.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    assert settings.auth_enabled is True
    return settings
