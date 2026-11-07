"""Frozen error-code catalogue and the API exception type.

This module is the single source of truth for section 4.3 of
`JC2001-Group4-协作与统一标准手册.md`, which M1 owns and which is FROZEN:
changing it requires a contract-review PR, not a casual edit.

Code format (5 digits):

    d1      category      1=request/validation  2=business conflict
                          3=auth/permission     4=not found   5=server
    d2-d3   module        00 common   01 auth   02 reservation  03 menu/order
                          04 membership  05 review  06 analytics
                          07 staff backend  08 database layer
    d4-d5   sequence      assigned by the module owner

Each module owner extends THEIR OWN number range only, via a PR that updates
both this file and section 4.3 of the manual. Do not invent codes ad hoc: two
modules picking the same number is exactly the kind of silent integration
failure the frozen table exists to prevent.

Why an exception carrying the code
----------------------------------
Services must be able to signal "this booking conflicts" without importing
FastAPI (see ARCHITECTURE.md section 3, the dependency rule). They raise
:class:`ApiError`; the router layer's exception handler turns it into the
frozen response envelope. A service that raised ``HTTPException`` directly
would be untestable without an HTTP layer and locked to one framework.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    """Every error code frozen in section 4.3 of the standards manual.

    Members are named ``CATEGORY_MODULE_MEANING`` so a reader can tell the
    category and owning module from the name alone.
    """

    # --- Success -----------------------------------------------------------
    OK = 0

    # --- 1xxxx request / validation (HTTP 400 or 422) ----------------------
    VALIDATION_FAILED = 10001
    """Pydantic rejected the request body, query or path parameters."""

    PAGINATION_OUT_OF_RANGE = 10002
    """`page_size` above 100, or a non-positive page number."""

    # --- 2xxxx business-rule conflict (HTTP 409 or 422) --------------------
    SLOT_ALREADY_BOOKED = 20001
    """The concurrency safety net fired: this table+slot is already taken.

    This is one of the two codes that constitute the project's external
    evidence of concurrency correctness. The acceptance test asserts that of 50
    simultaneous bookings for one table and slot, exactly one returns
    ``code: 0`` and the other 49 return ``20001``.
    """

    SEAT_HOLD_EXPIRED = 20002
    """The temporary hold timed out before confirmation."""

    ILLEGAL_STATUS_TRANSITION = 20003
    """The requested state-machine transition is not in ALLOWED_TRANSITIONS."""

    STALE_VERSION = 20004
    """Optimistic-lock conflict: the row changed since the client read it.

    The other of the two concurrency-evidence codes. Raised when SQLAlchemy's
    ``version_id_col`` check affects zero rows.
    """

    # --- 3xxxx authentication / authorisation (HTTP 401 or 403) ------------
    CREDENTIALS_MISSING = 30001
    """No Authorization header, or it is not a Bearer token."""

    CREDENTIALS_INVALID = 30002
    """Token is malformed, forged, expired, or carries an unknown role."""

    PERMISSION_DENIED = 30003
    """Token is valid but the role is not allowed for this endpoint."""

    # --- 4xxxx not found (HTTP 404) ----------------------------------------
    RESOURCE_NOT_FOUND = 40001

    # --- 5xxxx server (HTTP 500) -------------------------------------------
    INTERNAL_ERROR = 50001
    """Uncaught exception. The server log MUST carry the same request_id."""

    DATABASE_ERROR = 50002
    """Transaction rolled back due to a database failure."""


# Frozen (code -> HTTP status). Section 4.3 maps each category to a status;
# these are the per-code values the manual specifies.
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.OK: 200,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.PAGINATION_OUT_OF_RANGE: 400,
    ErrorCode.SLOT_ALREADY_BOOKED: 409,
    ErrorCode.SEAT_HOLD_EXPIRED: 409,
    ErrorCode.ILLEGAL_STATUS_TRANSITION: 422,
    ErrorCode.STALE_VERSION: 409,
    ErrorCode.CREDENTIALS_MISSING: 401,
    ErrorCode.CREDENTIALS_INVALID: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DATABASE_ERROR: 500,
}

# Frozen (code -> message). Reproduced verbatim from the manual's table so the
# API, the documentation and the frontend all show identical wording. The
# messages are Chinese because that is what the frozen contract specifies;
# changing the language is a contract change and needs group agreement.
MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.OK: "ok",
    ErrorCode.VALIDATION_FAILED: "请求参数校验失败",
    ErrorCode.PAGINATION_OUT_OF_RANGE: "分页参数超出允许范围",
    ErrorCode.SLOT_ALREADY_BOOKED: "该时段该餐桌已被预订",
    ErrorCode.SEAT_HOLD_EXPIRED: "座位临时锁定已过期",
    ErrorCode.ILLEGAL_STATUS_TRANSITION: "预订状态不允许该流转",
    ErrorCode.STALE_VERSION: "数据已被其他请求修改，请刷新后重试",
    ErrorCode.CREDENTIALS_MISSING: "未提供认证凭据",
    ErrorCode.CREDENTIALS_INVALID: "认证凭据无效或已过期",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.DATABASE_ERROR: "数据库操作失败",
}

# The two codes that prove concurrency correctness. Kept as a named set so the
# concurrency test and the technical report can reference them symbolically
# instead of hardcoding numbers that could drift.
CONCURRENCY_EVIDENCE_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.SLOT_ALREADY_BOOKED, ErrorCode.STALE_VERSION}
)


def http_status_for(code: ErrorCode) -> int:
    """Return the frozen HTTP status for an error code.

    Raises:
        KeyError: if the code is not in the frozen table. Failing loudly here is
            correct — an unmapped code means someone added an ErrorCode member
            without updating the contract, and silently defaulting to 500 would
            hide that from review.
    """
    return HTTP_STATUS[code]


def message_for(code: ErrorCode) -> str:
    """Return the frozen user-facing message for an error code."""
    return MESSAGES[code]


class ApiError(Exception):
    """A domain error that maps onto the frozen response envelope.

    Services raise this; they never raise ``HTTPException`` (that would couple
    the application tier to FastAPI — see ARCHITECTURE.md section 3).

    Example, from the reservation service:

        raise ApiError(ErrorCode.SLOT_ALREADY_BOOKED)

    or with field-level detail for the client to highlight:

        raise ApiError(
            ErrorCode.SLOT_ALREADY_BOOKED,
            errors=[{"field": "slot_id", "detail": "conflict with reservation #1024"}],
        )

    Attributes:
        code: the frozen ErrorCode.
        message: user-facing text; defaults to the frozen message for the code.
            Override only with group agreement, since the frontend and the
            technical report quote these strings.
        errors: optional field-level detail, rendered as the envelope's
            ``errors`` array.
        http_status: the frozen status for the code, overridable in the rare
            case one code legitimately maps to two statuses.
        data: almost always None on an error; present for symmetry with the
            success envelope.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        message: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        http_status: int | None = None,
        data: Any = None,
    ) -> None:
        self.code = code
        self.message = message if message is not None else message_for(code)
        self.errors = errors
        self.http_status = http_status if http_status is not None else http_status_for(code)
        self.data = data
        super().__init__(f"{int(code)}: {self.message}")


# ---------------------------------------------------------------------------
# Convenience constructors for the cases every module hits.
# ---------------------------------------------------------------------------


def not_found(message: str | None = None) -> ApiError:
    """40001 — the resource does not exist."""
    return ApiError(ErrorCode.RESOURCE_NOT_FOUND, message=message)


def validation_failed(
    errors: list[dict[str, Any]] | None = None,
    message: str | None = None,
) -> ApiError:
    """10001 — request validation failed."""
    return ApiError(ErrorCode.VALIDATION_FAILED, message=message, errors=errors)


def permission_denied(message: str | None = None) -> ApiError:
    """30003 — valid token, insufficient role.

    Note the deliberate asymmetry with :func:`unauthenticated`: 403 means "we
    know who you are and you may not do this", 401 means "we do not know who
    you are". Collapsing them makes the frontend unable to decide between
    redirecting to login and showing a permission notice.
    """
    return ApiError(ErrorCode.PERMISSION_DENIED, message=message)


def unauthenticated(code: ErrorCode = ErrorCode.CREDENTIALS_MISSING) -> ApiError:
    """30001 (no token) or 30002 (bad token)."""
    return ApiError(code)


def slot_conflict(detail: str | None = None) -> ApiError:
    """20001 — the concurrency safety net fired."""
    errors = [{"field": "slot_id", "detail": detail}] if detail else None
    return ApiError(ErrorCode.SLOT_ALREADY_BOOKED, errors=errors)


def stale_version() -> ApiError:
    """20004 — optimistic-lock conflict."""
    return ApiError(ErrorCode.STALE_VERSION)


def illegal_transition(detail: str | None = None) -> ApiError:
    """20003 — the state machine rejects this transition."""
    errors = [{"field": "status", "detail": detail}] if detail else None
    return ApiError(ErrorCode.ILLEGAL_STATUS_TRANSITION, errors=errors)
