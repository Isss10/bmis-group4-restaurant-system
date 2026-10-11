"""FastAPI application factory.

Run locally:

    uvicorn src.presentation.api.main:app --reload

The OpenAPI document this exposes at `/docs` and `/openapi.json` **is** the
"documented REST API" deliverable required by Objective (f). Export a snapshot
for the archive with:

    python scripts/export_openapi.py
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, status
from pydantic import BaseModel

from src.common.config import Settings, get_settings
from src.common.middleware import configure_logging, register_middleware
from src.common.security import CurrentUser, Role
from src.data.database import reset_engine

logger = logging.getLogger(__name__)

_DESCRIPTION = """
Restaurant reservation and food-ordering system — JC2001 BMIS Group 4.

**Modules**

| Module | Base path | Objective |
|--------|-----------|-----------|
| Health & metadata | `/health` | — |
| Reservation (seat booking, holds, state machine) | `/api/v1/reservations` | (a) |
| Ordering (menu browsing, order submission) | `/api/v1/orders` | (a) |
| Staff backend (reservation list, status, orders) | `/api/v1/staff` | (b) |
| Membership & loyalty (auth, points, tiers, coupons) | `/api/v1/membership` | (c) |
| Ratings & reviews (order-verified, Bayesian ranking) | `/api/v1/reviews` | (c) |
| Analytics (manager dashboard, recommender) | `/api/v1/analytics` | (e) |

**Authentication** — JWT bearer tokens. Click *Authorize* and paste the token
returned by the login endpoint. Roles: `customer`, `waiter`, `manager`, `admin`.

**Errors** — every error response has the shape
`{"error": {"code": <int>, "message": <str>, "request_id": <str>}}`.
Quote the `request_id` when reporting a problem; it links the response to the
server log and to any audit record.
"""


class HealthResponse(BaseModel):
    """Liveness/readiness payload."""

    status: str
    """`ok` when the process is healthy."""

    app: str
    version: str
    environment: str
    """`development`, `testing` or `production` — never expose more than this."""


class ServiceStatus(BaseModel):
    """Per-dependency status for the readiness probe."""

    name: str
    status: str
    detail: str | None = None


class CurrentIdentity(BaseModel):
    """What `/api/v1/auth/me` returns about the caller.

    Deliberately narrow. It is the minimum the SPA needs to render the right
    navigation and to decide whether to refresh the token — and it is derived
    from a *verified* token rather than from anything the client sends.

    No email, no points balance, no membership tier: those belong to the
    membership module's own endpoints, and returning them here would let every
    frontend depend on a shape the membership owner has to keep stable.
    """

    user_id: str
    """The token's `sub` claim — the user's id as a string."""

    role: Role
    """One of `customer`, `waiter`, `manager`, `admin`. Drives UI navigation."""

    token_id: str
    """The `jti` claim, so a compromised token can be revoked by id."""

    expires_at: int
    """Expiry as a POSIX timestamp; lets the client refresh before it lapses."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown hooks.

    Shutdown disposes the engine. Without this, every `--reload` cycle leaks a
    connection pool and MySQL eventually hits `max_connections`.
    """
    settings: Settings = app.state.settings
    logger.info(
        "Starting %s v%s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    # A development secret that reached production would let anyone forge
    # tokens. Say so loudly at startup rather than at incident time.
    if settings.environment == "development" and not settings.jwt_secret_key:
        logger.warning(
            "APP_JWT_SECRET_KEY is empty. Token creation will fail until it is set. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    yield
    logger.info("Shutting down: disposing database engine")
    reset_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    A factory (rather than a module-level `app = FastAPI()`) so tests can build
    an isolated instance with overridden settings and no shared global state.
    """
    cfg = settings or get_settings()
    configure_logging(cfg)

    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description=_DESCRIPTION,
        lifespan=lifespan,
        # Hide the framework's own /openapi.json and /docs in production: an
        # interactive API console should not be public on a live system.
        docs_url="/docs" if not cfg.is_production else None,
        redoc_url="/redoc" if not cfg.is_production else None,
        openapi_url="/openapi.json" if not cfg.is_production else None,
        # Do not leak the framework version in error pages.
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.state.settings = cfg

    register_middleware(app, cfg)
    app.include_router(_build_root_router(cfg))
    app.include_router(_build_health_router())
    app.include_router(_build_auth_router())

    # Module routers are imported lazily inside this function so that a syntax
    # error in one module does not prevent the health endpoint from starting —
    # useful when Docker health checks gate the rest of the stack.
    _register_module_routers(app)

    return app


def _build_root_router(cfg: Settings) -> APIRouter:
    """Root endpoint: a minimal machine-readable index."""
    router = APIRouter(tags=["meta"])

    @router.get("/", summary="Service index", response_model=dict[str, Any])
    async def root() -> dict[str, Any]:
        """Return the service name, version and the API base path.

        Deliberately discloses nothing beyond what is already public in the
        repository.
        """
        return {
            "service": cfg.app_name,
            "version": cfg.app_version,
            "api_base": "/api/v1",
            "docs": "/docs",
        }

    return router


def _build_health_router() -> APIRouter:
    """Health endpoints for Docker and CI smoke tests."""
    router = APIRouter(tags=["health"])

    @router.get(
        "/health",
        summary="Liveness probe",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
    )
    async def health(request: Request) -> HealthResponse:
        """Return process liveness without touching the database.

        Kept dependency-free on purpose: when MySQL is down we still want the
        container to report that the *process* is alive, so the orchestrator
        restarts the database rather than killing the API in a loop.

        Settings are read from `app.state`, not from `get_settings()`, so an app
        built with custom settings (tests) reports its own environment rather
        than the process-wide one.
        """
        cfg: Settings = request.app.state.settings
        return HealthResponse(
            status="ok",
            app=cfg.app_name,
            version=cfg.app_version,
            environment=cfg.environment,
        )

    return router


def _build_auth_router() -> APIRouter:
    """Identity endpoint every SPA needs after login.

    The Vue apps store a token and must confirm two things on page load: is it
    still valid, and which role does it carry (that decides whether to render the
    staff or manager navigation). Without this endpoint each frontend would
    invent its own way of decoding the JWT client-side — and decoding without
    verifying signature is how a tampered token gets trusted.

    It also has a useful side effect for the documentation deliverable: because
    this route genuinely depends on the bearer scheme, FastAPI emits the
    `securitySchemes` block in `/openapi.json`. A schema with no authenticated
    route documents nothing about how auth works.
    """
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    @router.get(
        "/me",
        summary="Current identity",
        response_model=CurrentIdentity,
        responses={
            401: {"description": "Missing, malformed or expired token"},
        },
    )
    async def me(identity: CurrentUser) -> CurrentIdentity:
        """Return the caller's id, role and token expiry.

        Requires a valid bearer token. Returns 401 with
        `WWW-Authenticate: Bearer` (RFC 6750 §3) when it is absent or invalid.
        """
        return CurrentIdentity(
            user_id=identity.sub,
            role=identity.role,
            token_id=identity.jti,
            expires_at=identity.exp,
        )

    return router


def _register_module_routers(app: FastAPI) -> None:
    """Attach each module's router under /api/v1, tolerating missing modules.

    The five modules are being implemented in parallel by different people
    (see README §6). A module whose router does not exist yet must not break
    the whole application, so import failures are logged and skipped. Remove
    the try/except once all five modules have landed and CI covers them.
    """
    module_paths = {
        "reservation": "src.application.reservation.router",
        "ordering": "src.application.ordering.router",
        "membership": "src.application.membership.router",
        "review": "src.application.review.router",
        "analytics": "src.application.analytics.router",
    }

    import importlib

    for name, path in module_paths.items():
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError:
            logger.debug("Module router not implemented yet: %s (%s)", name, path)
            continue
        except Exception:  # a broken module must not sink the app
            logger.exception("Failed to import router for module %s", name)
            continue

        router = getattr(module, "router", None)
        if router is None:
            logger.warning("Module %s has no `router` attribute; skipped", name)
            continue

        app.include_router(router, prefix=f"/api/v1/{name}", tags=[name])
        logger.info("Registered router for module %s at /api/v1/%s", name, name)


# The ASGI entry point used by uvicorn and by the Dockerfile.
app = create_app()
