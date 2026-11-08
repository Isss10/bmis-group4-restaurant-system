"""Member10 auth and account administration routes; preserve main's response contract."""

from __future__ import annotations

import secrets
from collections.abc import Generator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from src.application.membership.service import (
    LoginResult,
    MembershipError,
    MembershipService,
    csrf_for,
    user_out,
)
from src.common.envelope import Envelope, failure, paginate, success
from src.common.errors import ErrorCode, message_for
from src.common.security import CurrentUser, InvalidTokenError, Role, TokenPayload, require_roles
from src.data.database import get_session_factory
from src.data.repository.membership import MembershipRepository

REFRESH_COOKIE = "restaurant_refresh"
COOKIE_PATH = "/api/v1/auth"
# Auth/admin use their frozen /api/v1 paths; the shared loader separately
# mounts `router` at /api/v1/membership. Do not prefix the same router twice.
auth_router = APIRouter(prefix="/api/v1", tags=["membership"])
router = APIRouter(tags=["membership"])
limiter = Limiter(key_func=get_remote_address)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: EmailStr = Field(max_length=254)
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 12 or len(raw.encode("utf-8")) > 72:
            raise ValueError("Use at least 12 characters and at most 72 UTF-8 bytes")
        return value

    @field_validator("display_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name cannot be blank")
        return value.strip()


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)
    password: SecretStr

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value() or len(value.get_secret_value().encode("utf-8")) > 72:
            raise ValueError("Password must contain 1 to 72 UTF-8 bytes")
        return value


class CreateUserIn(RegisterIn):
    role: Role


class RoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    version: int = Field(ge=1)


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool = Field(strict=True)
    version: int = Field(ge=1)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: Role
    is_active: bool
    version: int


class LoginOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    csrf_token: str
    user: UserOut


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
    total_pages: int


def membership_session(request: Request) -> Generator[Session, None, None]:
    factory = getattr(request.app.state, "membership_session_factory", None)
    factory = factory or get_session_factory(request.app.state.settings)
    with factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def service(
    request: Request, session: Annotated[Session, Depends(membership_session)]
) -> MembershipService:
    return MembershipService(MembershipRepository(session), request.app.state.settings)


Service = Annotated[MembershipService, Depends(service)]
Admin = Annotated[TokenPayload, Depends(require_roles(Role.ADMIN))]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _origin(request: Request, *, required: bool = False) -> None:
    origin = request.headers.get("origin")
    allowed = set(request.app.state.settings.cors_origin_list)
    allowed.add(str(request.base_url).rstrip("/"))
    if (required and not origin) or (origin and origin not in allowed):
        raise HTTPException(403, "Untrusted request origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site session request rejected")


def _csrf(request: Request) -> str | None:
    _origin(request)
    refresh = request.cookies.get(REFRESH_COOKIE)
    if refresh:
        supplied = request.headers.get("x-csrf-token", "")
        expected = csrf_for(refresh, request.app.state.settings)
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(403, "Invalid CSRF token")
    return refresh


def _login_response(request: Request, response: Response, result: LoginResult) -> dict[str, Any]:
    response.set_cookie(
        REFRESH_COOKIE,
        result.refresh,
        max_age=result.max_age,
        httponly=True,
        secure=request.app.state.settings.is_production,
        samesite="strict",
        path=COOKIE_PATH,
    )
    _no_store(response)
    return success(result.data, request_id=getattr(request.state, "request_id", None))


@auth_router.post("/auth/register", response_model=Envelope[UserOut], status_code=201)
@limiter.limit("5/minute")
def register(
    request: Request, response: Response, body: RegisterIn, svc: Service
) -> dict[str, Any]:
    _origin(request)
    _no_store(response)
    data = svc.register(
        email=str(body.email),
        password=body.password.get_secret_value(),
        display_name=body.display_name,
    )
    return success(data, request_id=getattr(request.state, "request_id", None))


@auth_router.post("/auth/login", response_model=Envelope[LoginOut])
@limiter.limit("5/minute")
def login(request: Request, response: Response, body: LoginIn, svc: Service) -> dict[str, Any]:
    _origin(request)
    result = svc.login(str(body.email), body.password.get_secret_value())
    return _login_response(request, response, result)


@auth_router.get("/auth/csrf", response_model=Envelope[dict[str, str]])
def csrf(request: Request, response: Response) -> dict[str, Any]:
    _origin(request)
    refresh = request.cookies.get(REFRESH_COOKIE)
    if not refresh:
        raise MembershipError(401, "Not authenticated", code=ErrorCode.CREDENTIALS_MISSING)
    _no_store(response)
    return success(
        {"csrf_token": csrf_for(refresh, request.app.state.settings)},
        request_id=getattr(request.state, "request_id", None),
    )


@auth_router.post("/auth/refresh", response_model=Envelope[LoginOut])
def refresh_session(request: Request, response: Response, svc: Service) -> dict[str, Any]:
    refresh = _csrf(request)
    if not refresh or len(refresh) > 256:
        raise MembershipError(401, "Invalid credentials")
    return _login_response(request, response, svc.refresh(refresh))


@auth_router.post("/auth/logout", response_model=Envelope[dict[str, bool]])
def logout(request: Request, response: Response, svc: Service) -> dict[str, Any]:
    svc.logout(_csrf(request))
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=request.app.state.settings.is_production,
        samesite="strict",
    )
    _no_store(response)
    return success({"logged_out": True}, request_id=getattr(request.state, "request_id", None))


@router.get("/profile", response_model=Envelope[UserOut])
def profile(
    request: Request, response: Response, identity: CurrentUser, svc: Service
) -> dict[str, Any]:
    _no_store(response)
    return success(
        user_out(svc.validate_identity(identity)),
        request_id=getattr(request.state, "request_id", None),
    )


@auth_router.get("/users", response_model=Envelope[UserPage])
def users(
    request: Request,
    response: Response,
    identity: Admin,
    svc: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    _no_store(response)
    return success(
        paginate(
            [
                user_out(user)
                for user in svc.repo.list_users(
                    offset=(page - 1) * page_size,
                    limit=page_size,
                )
            ],
            total=svc.repo.user_count(),
            page=page,
            page_size=page_size,
        ),
        request_id=getattr(request.state, "request_id", None),
    )


@auth_router.post("/users", response_model=Envelope[UserOut], status_code=201)
def create_user(
    request: Request,
    response: Response,
    body: CreateUserIn,
    identity: Admin,
    svc: Service,
) -> dict[str, Any]:
    _no_store(response)
    data = svc.register(
        email=str(body.email),
        password=body.password.get_secret_value(),
        display_name=body.display_name,
        role=body.role,
        actor=identity,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(data, request_id=getattr(request.state, "request_id", None))


@auth_router.patch("/users/{user_id}/role", response_model=Envelope[UserOut])
def change_role(
    request: Request,
    response: Response,
    user_id: int,
    body: RoleIn,
    identity: Admin,
    svc: Service,
) -> dict[str, Any]:
    _no_store(response)
    data = svc.change_user(
        user_id,
        actor=identity,
        role=body.role,
        version=body.version,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(data, request_id=getattr(request.state, "request_id", None))


@auth_router.patch("/users/{user_id}/status", response_model=Envelope[UserOut])
def change_status(
    request: Request,
    response: Response,
    user_id: int,
    body: StatusIn,
    identity: Admin,
    svc: Service,
) -> dict[str, Any]:
    _no_store(response)
    data = svc.change_user(
        user_id,
        actor=identity,
        is_active=body.is_active,
        version=body.version,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(data, request_id=getattr(request.state, "request_id", None))


def install_membership(app: Any) -> None:
    """One validator shared by all guards, including existing module routes."""

    def validate(payload: TokenPayload) -> None:
        factory = getattr(app.state, "membership_session_factory", None)
        factory = factory or get_session_factory(app.state.settings)
        # Session-less legacy tokens fail closed without attempting a DB connection.
        if not payload.sid or payload.auth_version is None:
            raise InvalidTokenError("Session is required")
        with factory() as session:
            MembershipService(MembershipRepository(session), app.state.settings).validate_identity(
                payload
            )

    async def member_error(request: Request, exc: MembershipError) -> JSONResponse:
        headers = {"Cache-Control": "no-store"}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        code = exc.code or {
            401: ErrorCode.CREDENTIALS_INVALID,
            403: ErrorCode.PERMISSION_DENIED,
            404: ErrorCode.RESOURCE_NOT_FOUND,
        }.get(exc.status, ErrorCode.VALIDATION_FAILED)
        # Reuse the frozen catalogue; account-rule conflicts do not invent new
        # codes or masquerade as an optimistic-lock failure.
        detail = None
        if code == ErrorCode.VALIDATION_FAILED:
            detail = [{"field": "account", "detail": exc.message}]
        return JSONResponse(
            status_code=exc.status,
            content=failure(
                code,
                request_id=getattr(request.state, "request_id", None),
                errors=detail,
            ),
            headers=headers,
        )

    async def rate_error(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        # The frozen catalogue has no rate-limit code. Preserve HTTP 429 and
        # Retry-After, and provide field detail under existing validation 10001.
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60", "Cache-Control": "no-store"},
            content=failure(
                ErrorCode.VALIDATION_FAILED,
                request_id=getattr(request.state, "request_id", None),
                errors=[{"field": "request", "detail": "Too many attempts; retry later"}],
            ),
        )

    async def revoked_identity(request: Request, exc: InvalidTokenError) -> JSONResponse:
        return await member_error(
            request, MembershipError(401, message_for(ErrorCode.CREDENTIALS_INVALID))
        )

    app.state.auth_validator = validate
    limiter.enabled = app.state.settings.rate_limit_enabled
    app.state.limiter = limiter
    app.add_exception_handler(MembershipError, member_error)
    app.add_exception_handler(InvalidTokenError, revoked_identity)
    app.add_exception_handler(RateLimitExceeded, rate_error)
    app.include_router(auth_router)
