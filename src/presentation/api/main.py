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
from src.common.envelope import Envelope
from src.common.middleware import REQUEST_ID_ATTR, configure_logging, register_middleware
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

**Envelope** — every response, success or failure, has the shape

    {"code": 0, "message": "ok", "data": {...},
     "request_id": "…", "timestamp": "2026-10-11T12:30:00Z"}

`code` is **0 on success** and a 5-digit business code on failure (`20001` slot
already booked, `30003` permission denied, `50001` internal error, …). It is not
the HTTP status: the status tells your HTTP client what happened at the transport
level, while `code` tells your application *which* rule was violated. Switch on
`code`, not on the status. Failures may also carry
`errors: [{"field": …, "detail": …}]` for field-level highlighting.

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
    """Health endpoints for Docker and CI smoke tests.

    Two paths are registered deliberately:

    * ``/api/v1/health`` is the contract path (manual §4.1 prefix rule and the
      Wave-1 acceptance criterion "`/api/v1/health` returns 200"). Anything
      documented or graded uses this one.
    * ``/health`` is the conventional location orchestrators expect. The
      Dockerfile HEALTHCHECK and the CI docker-job smoke test both curl it, and
      moving it would break container health reporting. It is an alias, not a
      second implementation — one handler, two routes, so they cannot drift.
    """
    router = APIRouter(tags=["health"])

    # Two stacked decorators, not two paths in one call: `APIRouter.get()` takes
    # exactly one positional path, so `@router.get("/a", "/b")` raises TypeError.
    # Stacking works because FastAPI's route decorator returns the function
    # unchanged, so the inner decorator registers `/health` and hands the same
    # function to the outer one, which registers `/api/v1/health`. One
    # implementation, two routes — they cannot drift apart.
    @router.get(
        "/api/v1/health",
        summary="Liveness probe",
        response_model=Envelope[HealthResponse],
        status_code=status.HTTP_200_OK,
    )
    @router.get(
        "/health",
        summary="Liveness probe (alias)",
        response_model=Envelope[HealthResponse],
        status_code=status.HTTP_200_OK,
        # Keep the alias out of the generated OpenAPI document: it exists for
        # infrastructure, and documenting two health endpoints invites the
        # frontend to use the non-contract one.
        include_in_schema=False,
    )
    async def health(request: Request) -> Envelope[HealthResponse]:
        """Return process liveness without touching the database.

        Kept dependency-free on purpose: when MySQL is down we still want the
        container to report that the *process* is alive, so the orchestrator
        restarts the database rather than killing the API in a loop.

        Settings are read from `app.state`, not from `get_settings()`, so an app
        built with custom settings (tests) reports its own environment rather
        than the process-wide one.

        Wrapped in the frozen envelope like every other endpoint (manual §4.2),
        so the health payload is under ``data``. The container HEALTHCHECK only
        asserts an HTTP 200, so the wrapper does not disturb it.
        """
        cfg: Settings = request.app.state.settings
        payload = HealthResponse(
            status="ok",
            app=cfg.app_name,
            version=cfg.app_version,
            environment=cfg.environment,
        )
        return Envelope[HealthResponse](
            code=0,
            message="ok",
            data=payload,
            request_id=getattr(request.state, REQUEST_ID_ATTR, None),
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
        response_model=Envelope[CurrentIdentity],
        responses={
            401: {"description": "Missing (30001) or invalid/expired (30002) token"},
        },
    )
    async def me(request: Request, identity: CurrentUser) -> Envelope[CurrentIdentity]:
        """Return the caller's id, role and token expiry.

        Requires a valid bearer token. Returns 401 with
        `WWW-Authenticate: Bearer` (RFC 6750 §3) when it is absent or invalid,
        carrying code 30001 or 30002 so the frontend can tell "never logged in"
        from "session lapsed".
        """
        payload = CurrentIdentity(
            user_id=identity.sub,
            role=identity.role,
            token_id=identity.jti,
            expires_at=identity.exp,
        )
        return Envelope[CurrentIdentity](
            code=0,
            message="ok",
            data=payload,
            request_id=getattr(request.state, REQUEST_ID_ATTR, None),
        )

    return router


# Frozen module → (router module path, base path).
#
# Both halves of this mapping are contract, not convention, and the two are
# deliberately written out rather than derived:
#
# * **Router location** is `src/presentation/api/routers/<module>.py`, per
#   ARCHITECTURE.md §2 (the ASCII diagram lists `api/routers/  one router per
#   module`) and §3's dependency rule — the application tier "Must NOT import
#   `fastapi`", so a router cannot live there. §6 names this directory as the
#   REST API contract boundary owned by YAN ZHANG.
# * **Base path** is spelled out because the module *directory* is singular
#   (`reservation/`) while the frozen API path is plural
#   (`/api/v1/reservations`, manual §4.2 "plural nouns"; also the table in
#   `_DESCRIPTION` above and ARCHITECTURE.md §2). Deriving the prefix from the
#   directory name produced `/api/v1/reservation` — a path no document ever
#   advertised, so all three Vue apps would 404 while every CI job stayed
#   green, because nothing asserted the mounted prefix.
#
# `tests/unit/test_router_registration.py` pins this mapping. Changing a base
# path means changing that test *and* the documents above, in one PR.
_MODULE_ROUTERS: dict[str, tuple[str, str]] = {
    "reservation": ("src.presentation.api.routers.reservation", "/api/v1/reservations"),
    "ordering": ("src.presentation.api.routers.ordering", "/api/v1/orders"),
    "staff": ("src.presentation.api.routers.staff", "/api/v1/staff"),
    "membership": ("src.presentation.api.routers.membership", "/api/v1/membership"),
    "review": ("src.presentation.api.routers.review", "/api/v1/reviews"),
    "analytics": ("src.presentation.api.routers.analytics", "/api/v1/analytics"),
}


def _register_module_routers(app: FastAPI) -> None:
    """Attach each module's router at its frozen base path, tolerating absences.

    The modules are being implemented in parallel by different people (see
    README §6). A module whose router does not exist yet must not break the
    whole application, so import failures are logged and skipped — that is why
    `/health` starts even with an empty repository. Remove the try/except once
    every module has landed and CI covers them.

    A router that *exists* but is malformed is louder than one that is missing:
    the exception is logged with a traceback rather than swallowed, because a
    typo in a merged module should be visible in the container log.

    `include_router` is inside the try as well. Importing cleanly is not the
    same as mounting cleanly — a module that exports something which is not an
    APIRouter (or a router with a decorator FastAPI rejects) raises here, and
    without this the whole application fails to start: `/health` never comes
    up, so Docker's health check fails and the container restarts in a loop.
    One module's typo must not take the entire API down with it.
    """
    import importlib

    for name, (path, prefix) in _MODULE_ROUTERS.items():
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

        try:
            app.include_router(router, prefix=prefix, tags=[name])
        except Exception:
            logger.exception(
                "Router for module %s imported but could not be mounted at %s; skipped",
                name,
                prefix,
            )
            continue
        logger.info("Registered router for module %s at %s", name, prefix)


# The ASGI entry point used by uvicorn and by the Dockerfile.
app = create_app()
