"""Authentication, authorisation and password security.

Implements the role-based access control required by Objective (c):
four roles — customer, waiter, manager, admin.

Design notes
------------
* Passwords are hashed with bcrypt via passlib. **Never store or log a
  plaintext password** (OWASP A02:2021 Cryptographic Failures).
* Tokens are stateless JWTs signed with HS256. The secret comes from
  environment configuration only — a hardcoded fallback would be a critical
  vulnerability (OWASP A02/A07).
* Authorisation is enforced by dependency-injected guards, so a route cannot
  accidentally be left public: you must name the roles you accept.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, NoReturn

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel

from src.common.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(StrEnum):
    """System roles, ordered from least to most privileged.

    `StrEnum` means the value used in JWT claims and database columns is the
    plain lowercase string ("manager"), while code compares against the enum
    and cannot typo a role name.
    """

    CUSTOMER = "customer"
    WAITER = "waiter"
    MANAGER = "manager"
    ADMIN = "admin"

    @property
    def is_staff(self) -> bool:
        """True for any role that operates the restaurant back office."""
        return self in {Role.WAITER, Role.MANAGER, Role.ADMIN}


# Roles allowed to moderate reviews and see the moderation queue.
REVIEW_MODERATORS: frozenset[Role] = frozenset({Role.WAITER, Role.MANAGER, Role.ADMIN})
# Roles allowed to see the analytics dashboard (Objective e).
ANALYTICS_VIEWERS: frozenset[Role] = frozenset({Role.MANAGER, Role.ADMIN})


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# bcrypt is capped at 72 bytes by design; passlib truncates silently beyond
# that. We reject longer passwords instead of silently weakening them.
_BCRYPT_MAX_BYTES = 72

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return a salted bcrypt hash of `plain_password`.

    Raises:
        ValueError: if the password is empty or longer than bcrypt supports.
    """
    if not plain_password:
        msg = "Password must not be empty"
        raise ValueError(msg)
    encoded = plain_password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        msg = (
            f"Password must be at most {_BCRYPT_MAX_BYTES} bytes when UTF-8 encoded "
            f"(got {len(encoded)}). This is a bcrypt limitation, not an arbitrary rule."
        )
        raise ValueError(msg)
    hashed: str = _pwd_context.hash(plain_password)
    return hashed


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash.

    Returns False instead of raising when the hash is malformed, so a corrupt
    row cannot be turned into a 500 that leaks internals.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bool(_pwd_context.verify(plain_password, hashed_password))
    except (ValueError, TypeError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    """True if the stored hash uses outdated parameters and should be upgraded."""
    try:
        return bool(_pwd_context.needs_update(hashed_password))
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


class TokenPayload(BaseModel):
    """The claims we put inside an access token."""

    sub: str
    """Subject — the user id. Kept as a string so it works for int and UUID ids."""

    role: Role
    """Authorisation role, checked by the guards below."""

    exp: int
    """Expiry as a POSIX timestamp, validated automatically by PyJWT."""

    iat: int
    """Issued-at timestamp."""

    jti: str
    """Unique token id, so a leaked token can be revoked by id if needed."""


class TokenPair(BaseModel):
    """Issued token plus its expiry, returned to the client on login."""

    access_token: str
    # Not a secret: "bearer" is the fixed token-type literal defined by
    # RFC 6749 §7.1, which the client must receive so it knows to send
    # `Authorization: Bearer <token>`. bandit's S105 matches on the *name*
    # `token_type` and cannot tell a protocol constant from a credential.
    token_type: str = "bearer"  # noqa: S105 - OAuth2 RFC 6749 literal, not a secret
    expires_in: int
    """Lifetime in seconds — lets the client refresh before expiry."""


def create_access_token(
    *,
    user_id: str | int,
    role: Role | str,
    settings: Settings | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> TokenPair:
    """Sign a short-lived access token for `user_id`.

    The token carries only the minimum claims needed to authorise a request.
    Do **not** put personal data (email, phone, name) in a token: it is only
    base64-encoded, readable by anyone who intercepts it.
    """
    cfg = settings or get_settings()
    if not cfg.jwt_secret_key:
        # Refuse to sign with an empty secret rather than producing tokens that
        # any attacker can forge.
        msg = (
            "APP_JWT_SECRET_KEY is not configured. Generate one with "
            '`python -c "import secrets; print(secrets.token_urlsafe(48))"` '
            "and set it in .env"
        )
        raise RuntimeError(msg)

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=cfg.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": str(role),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        # Never let a caller override the security-critical claims.
        reserved = {"sub", "role", "iat", "exp", "jti"}
        overrides = set(extra_claims) & reserved
        if overrides:
            msg = f"extra_claims must not override reserved claims: {sorted(overrides)}"
            raise ValueError(msg)
        payload.update(extra_claims)

    token = jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm)
    return TokenPair(
        access_token=token,
        expires_in=int(cfg.access_token_expire_minutes * 60),
    )


def decode_access_token(token: str, settings: Settings | None = None) -> TokenPayload:
    """Verify signature and expiry, returning the decoded claims.

    Raises:
        InvalidTokenError: on any verification failure. Callers translate this
            into HTTP 401 without revealing *why* — a message like "token
            expired" vs "bad signature" helps an attacker (OWASP A07).
    """
    cfg = settings or get_settings()
    if not cfg.jwt_secret_key:
        msg = "APP_JWT_SECRET_KEY is not configured"
        raise InvalidTokenError(msg)
    try:
        raw = jwt.decode(
            token,
            cfg.jwt_secret_key,
            algorithms=[cfg.jwt_algorithm],
            options={
                "require": ["exp", "sub", "role", "iat"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_signature": True,
            },
        )
    except jwt.PyJWTError as exc:
        # Log the real reason internally, surface nothing to the client.
        raise InvalidTokenError("Token verification failed") from exc

    try:
        return TokenPayload.model_validate(raw)
    except Exception as exc:  # normalise any shape error to 401
        raise InvalidTokenError("Token claims are malformed") from exc


class InvalidTokenError(Exception):
    """Raised when a token is missing, malformed, expired or forged."""


# ---------------------------------------------------------------------------
# FastAPI dependencies (guards)
# ---------------------------------------------------------------------------

# auto_error=False so we produce our own 401 body instead of FastAPI's default,
# keeping error responses uniform across the API.
_bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


async def get_current_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> TokenPayload:
    """Extract and verify the bearer token from the Authorization header."""
    if credentials is None or not credentials.credentials:
        _unauthorised("Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        _unauthorised("Not authenticated")
    # Attach the identity to the request so audit logging can attribute the
    # action without threading the payload through every service call.
    request.state.current_user_id = payload.sub
    request.state.current_role = payload.role
    request.state.token_id = payload.jti
    return payload


def _unauthorised(detail: str) -> NoReturn:
    """Raise a 401 with the WWW-Authenticate header the RFC requires."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> NoReturn:
    """Raise a 403 — authenticated, but not permitted for this resource."""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


CurrentUser = Annotated[TokenPayload, Depends(get_current_token)]
"""Any authenticated user. Use this when the role does not matter."""


def require_roles(*roles: Role) -> Callable[..., Coroutine[Any, Any, TokenPayload]]:
    """Build a dependency that only accepts the listed roles.

    Example:
        @router.get("/analytics/revenue", dependencies=[Depends(require_roles(Role.MANAGER))])
        async def revenue(): ...

    A 403 (not 401) is returned for a valid token with the wrong role: the
    caller *is* authenticated, just not permitted (OWASP A01 Broken Access
    Control — this is the single highest-risk item in the Top 10 for this
    project, since waiters must not reach manager data).
    """
    if not roles:
        msg = "require_roles() needs at least one role, otherwise it permits nobody"
        raise ValueError(msg)
    allowed = frozenset(roles)

    async def guard(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    ) -> TokenPayload:
        payload = await get_current_token(request, credentials)
        if payload.role not in allowed:
            _forbidden("You do not have permission to perform this action")
        return payload

    return guard


def require_staff() -> Callable[..., Coroutine[Any, Any, TokenPayload]]:
    """Guard for any back-office role (waiter, manager or admin)."""
    return require_roles(Role.WAITER, Role.MANAGER, Role.ADMIN)


def require_review_moderator() -> Callable[..., Coroutine[Any, Any, TokenPayload]]:
    """Guard for the review moderation queue (Objective c)."""
    return require_roles(*sorted(REVIEW_MODERATORS, key=lambda r: r.value))


def require_analytics_viewer() -> Callable[..., Coroutine[Any, Any, TokenPayload]]:
    """Guard for the manager analytics dashboard (Objective e)."""
    return require_roles(*sorted(ANALYTICS_VIEWERS, key=lambda r: r.value))
