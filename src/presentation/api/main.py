"""FastAPI application factory. Run locally:
    uvicorn src.presentation.api.main:app --reload
The OpenAPI document this exposes at `/docs` and `/openapi.json`
**is** the "documented REST API" deliverable required by Objective (f).
Export a snapshot for the archive with:
    python scripts/export_openapi.py
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response, status
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
| Ordering (menu browsing, ordering submission) | `/api/v1/orders` | (a) |
| Staff backend (reservation list, status, orders) | `/api/v1/staff` | (b) |
| Membership & loyalty (auth, points, tiers, coupons) | `/api/v1/membership` | (c) |
| Ratings & reviews (ordering-verified, Bayesian ranking) | `/api/v1/reviews` | (c) |
| Analytics (manager dashboard, recommender) | `/api/v1/analytics` | (e) |

**Authentication** — JWT bearer tokens. Click *Authorize* and paste the token
returned by the login endpoint.
Roles: `customer`, `waiter`, `manager`, `admin`.

**Envelope** — every response, success or failure, has the shape
    {"code": 0, "message": "ok", "data": {...},
     "request_id": "…", "timestamp": "2026-10-11T12:30:00Z"}
`code` is **0 on success** and a 5-digit business code on failure
(`20001` slot already booked, `30003` permission denied, `50001` internal error, …).
It is not the HTTP status: the status tells your HTTP client what happened at
the transport level, while `code` tells your application *which* rule was violated.
Switch on `code`, not on the status. Failures may also carry
`errors: [{"field": …, "detail": …}]` for field-level highlighting.
Quote the `request_id` when reporting a problem; it links the response
to the server log and to any audit record.
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
    """What `/api/v1/auth/me` returns about the caller."""

    user_id: str
    role: Role
    token_id: str
    expires_at: int


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "Starting %s v%s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    if settings.environment == "development" and not settings.jwt_secret_key:
        logger.warning(
            "APP_JWT_SECRET_KEY is empty. Token creation will fail until it is set. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    yield
    logger.info("Shutting down: disposing database engine")
    reset_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg)
    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description=_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if not cfg.is_production else None,
        redoc_url="/redoc" if not cfg.is_production else None,
        openapi_url="/openapi.json" if not cfg.is_production else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.state.settings = cfg
    register_middleware(app, cfg)

    app.include_router(_build_root_router(cfg))
    app.include_router(_build_health_router())
    app.include_router(_build_auth_router())

    from src.presentation.api.routers.membership import install_membership

    install_membership(app)

    _register_module_routers(app)
    return app


def _build_root_router(cfg: Settings) -> APIRouter:
    router = APIRouter(tags=["meta"])

    @router.get("/", summary="Service index", response_model=dict[str, Any])
    async def root() -> dict[str, Any]:
        return {
            "service": cfg.app_name,
            "version": cfg.app_version,
            "api_base": "/api/v1",
            "docs": "/docs",
        }

    return router


def _build_health_router() -> APIRouter:
    router = APIRouter(tags=["health"])

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
        include_in_schema=False,
    )
    async def health(request: Request) -> Envelope[HealthResponse]:
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
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    @router.get(
        "/me",
        summary="Current identity",
        response_model=Envelope[CurrentIdentity],
        responses={
            401: {"description": "Missing (30001) or invalid/expired (30002) token"},
        },
    )
    async def me(
        request: Request, identity: CurrentUser, response: Response
    ) -> Envelope[CurrentIdentity]:
        response.headers["Cache-Control"] = "no-store"
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


_MODULE_ROUTERS: dict[str, tuple[str, str]] = {
    "reservation": ("src.presentation.api.routers.reservation", "/api/v1/reservations"),
    "ordering": ("src.presentation.api.routers.ordering", "/api/v1/orders"),
    "staff": ("src.presentation.api.routers.staff", "/api/v1/staff"),
    "membership": ("src.presentation.api.routers.membership", "/api/v1/membership"),
    "review": ("src.presentation.api.routers.review", "/api/v1/reviews"),
    "analytics": ("src.presentation.api.routers.analytics", "/api/v1/analytics"),
}


def _register_module_routers(app: FastAPI) -> None:
    import importlib

    for name, (path, prefix) in _MODULE_ROUTERS.items():
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError:
            logger.debug("Module router not implemented yet: %s (%s)", name, path)
            continue
        except Exception:
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


app = create_app()
