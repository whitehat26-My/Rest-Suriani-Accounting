"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import (
    accounts,
    auth,
    insights,
    inventory,
    payroll,
    reports,
    transactions,
    uploads,
)

logger = logging.getLogger("uvicorn.error")

DESCRIPTION = """
An accounting system for a small restaurant, built for two very different people.

**The owner** taps *Money In*, *Money Out* or *Count Stock*. She never sees a
debit or a credit.

**The accountant** gets a complete double-entry ledger, a trial balance, and the
three primary financial statements, generated from the very same taps.

The bridge between them is the event-driven posting engine in
`app/services/ledger.py`: every business event maps to a rule that produces a
balanced set of ledger entries.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create tables and make sure the chart of accounts exists."""
    init_db()
    from .seed import ensure_chart_of_accounts

    ensure_chart_of_accounts()

    # Refuse to start on a misconfiguration that would run the app open or break
    # sessions. In production this is fatal; in development it is a loud warning.
    problems = settings.validate_deployment()
    if problems:
        message = "Deployment configuration problems:\n  - " + "\n  - ".join(problems)
        if settings.is_production:
            raise RuntimeError(message)
        logger.warning(message)

    if not settings.auth_enabled:
        logger.warning(
            "Google sign-in is not configured, so every endpoint is open. "
            "This is fine on a laptop; set ENVIRONMENT=production plus the Google "
            "and SECRET_KEY values before putting this anywhere other people can reach."
        )
    if settings.auth_enabled and not settings.cookie_secure and not settings.is_production:
        logger.warning(
            "COOKIE_SECURE is off, so session cookies will be sent over plain "
            "http. Turn it on once the app is served over https."
        )
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline hardening headers on every response.

    These cost nothing and close off MIME-sniffing, clickjacking and referrer
    leakage. HSTS is only meaningful over HTTPS, so it is added only in
    production where the app is served over TLS.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Cache-Control", "no-store" if request.url.path.startswith("/api/") else "no-cache"
    )
    if request.url.path.startswith("/api/"):
        # The API only ever returns JSON or file downloads; nothing on it should
        # be framed, scripted, or embedded.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(inventory.router)
app.include_router(payroll.router)
app.include_router(reports.router)
app.include_router(insights.router)
app.include_router(uploads.router)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "business": settings.business_name,
        "currency": settings.currency,
        "database": "sqlite" if settings.is_sqlite else "postgresql",
    }


@app.get("/api/config", tags=["system"])
def client_config() -> dict:
    """Everything the frontend needs to render labels and currency."""
    from .chart_of_accounts import SPENDING_CATEGORIES

    return {
        "business_name": settings.business_name,
        "currency": settings.currency,
        "auth_enabled": settings.auth_enabled,
        "spending_categories": [
            {"slug": slug, "label": label, "emoji": emoji, "account_code": code}
            for slug, label, emoji, code in SPENDING_CATEGORIES
        ],
    }
