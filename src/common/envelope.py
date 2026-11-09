"""The frozen unified response envelope and pagination helper.

Implements section 4.2 of `JC2001-Group4-协作与统一标准手册.md`. The contract is
**mandatory on every endpoint**, which is precisely why it lives here rather than
being assembled per-router: ten people writing five modules cannot each remember
five fields in the same order.

Success envelope::

    {"code": 0, "message": "ok", "data": {...},
     "request_id": "req_8f3a2b1c", "timestamp": "2026-11-15T12:30:00Z"}

Failure envelope (``errors`` only present when there is field-level detail)::

    {"code": 20001, "message": "该时段该餐桌已被预订", "data": null,
     "errors": [{"field": "time_slot", "detail": "conflict with reservation #1024"}],
     "request_id": "req_8f3a2b1c", "timestamp": "2026-11-15T12:30:00Z"}

Paginated lists nest the page metadata inside ``data``::

    {"code": 0, "message": "ok",
     "data": {"items": [], "total": 137, "page": 1,
              "page_size": 20, "total_pages": 7}, ...}

Consequences of wrapping
------------------------
Because the payload is nested under ``data``, FastAPI's ``response_model``
validation applies to the *wrapper*, not to the resource. Declare models as
``Envelope[ReservationOut]`` (see :class:`Envelope`) so the generic keeps
type-checking the inner payload and the generated OpenAPI schema still shows the
real shape.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_serializer

from src.common.errors import ErrorCode, message_for

DataT = TypeVar("DataT")

# Contract query-parameter limits (section 4.2).
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 with a `Z` suffix.

    The frozen contract's example is ``2026-11-15T12:30:00Z``. Python's
    ``isoformat()`` emits ``+00:00`` instead of ``Z``, and the frontend TS types
    are generated from the contract, so normalise explicitly rather than letting
    two valid-but-different spellings coexist across ten modules.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FieldError(BaseModel):
    """One field-level validation or conflict detail.

    Field names follow the contract's spelling: ``field`` and ``detail``
    (note: ``detail``, not ``message`` — a subtle difference that is easy to get
    wrong and would break the frontend's error display).
    """

    field: str
    detail: str


class Envelope(BaseModel, Generic[DataT]):
    """The unified response wrapper.

    Generic over the payload so a router can declare
    ``response_model=Envelope[ReservationOut]`` and keep both static type
    checking and an accurate OpenAPI schema.
    """

    code: int = 0
    """0 on success; a frozen 5-digit ErrorCode on failure."""

    message: str = "ok"
    data: DataT | None = None
    """Always emitted, including as an explicit ``null`` on failure — the
    contract's error example carries ``"data": null``, and a client that reads
    ``body.data`` should not have to branch on whether the key exists."""

    request_id: str | None = None
    """Correlation id. Links the response to the server log and audit rows."""

    timestamp: str = Field(default_factory=utc_now_iso)
    errors: list[FieldError] | None = None
    """Field-level detail. Omitted entirely when there is none, rather than sent
    as ``null`` or ``[]``, so clients can test for presence."""

    @model_serializer(mode="wrap")
    def _omit_absent_errors(
        self, handler: Callable[[Envelope[DataT]], dict[str, Any]]
    ) -> dict[str, Any]:
        """Drop ``errors`` from the serialised body when it is None.

        The contract's success envelope is exactly
        ``{code, message, data, request_id, timestamp}`` — five keys, no
        ``errors``. Emitting ``"errors": null`` on every successful response
        would silently extend the contract for all ten modules and for the
        generated TypeScript types.

        This is done with a wrap serializer rather than
        ``model_config = ConfigDict(exclude_none=True)`` or FastAPI's
        ``response_model_exclude_none``: those are unconditional and would also
        strip ``data: null`` from *error* responses, which the contract
        explicitly requires. The omission has to be per-field, not per-model.

        In ``mode="wrap"`` pydantic calls this as ``handler(value)`` where
        ``value`` is the model instance; it returns the normally-serialised dict
        for us to adjust. Calling ``handler()`` with no argument raises
        ``TypeError``, which pydantic reports as a PydanticSerializationError and
        FastAPI turns into a 500 — so the signature is load-bearing, not
        stylistic.
        """
        payload = handler(self)
        if payload.get("errors") is None:
            payload.pop("errors", None)
        return payload


def success(
    data: Any = None,
    *,
    request_id: str | None = None,
    message: str = "ok",
) -> dict[str, Any]:
    """Build a success envelope as a plain dict.

    Returns a dict rather than an ``Envelope`` instance so it can carry
    arbitrary payloads (ORM objects already converted, nested dicts, lists)
    without a generic-parameter dance at every call site. Routers that want
    schema-level validation should declare ``response_model=Envelope[T]``.
    """
    body: dict[str, Any] = {
        "code": int(ErrorCode.OK),
        "message": message,
        "data": data,
        "request_id": request_id,
        "timestamp": utc_now_iso(),
    }
    return body


def failure(
    code: ErrorCode,
    *,
    request_id: str | None = None,
    message: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    data: Any = None,
) -> dict[str, Any]:
    """Build a failure envelope as a plain dict.

    ``errors`` is omitted when empty so the client can distinguish "no field
    detail available" from "these specific fields are wrong".
    """
    body: dict[str, Any] = {
        "code": int(code),
        "message": message if message is not None else message_for(code),
        "data": data,
        "request_id": request_id,
        "timestamp": utc_now_iso(),
    }
    if errors:
        body["errors"] = errors
    return body


class Page(BaseModel, Generic[DataT]):
    """The paginated ``data`` payload shape frozen by section 4.2."""

    items: list[DataT]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginate(
    items: list[Any],
    *,
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Assemble the paginated ``data`` object.

    ``total`` is passed in rather than derived from ``len(items)`` because the
    whole point is that ``items`` is one page of a larger result set. Callers
    get it from a ``SELECT COUNT(*)`` or ``Query.total()``.

    ``total_pages`` is computed with ceiling division and is at least 1 when
    ``total`` is 0, so a client dividing by it never hits a zero denominator.
    """
    if page_size <= 0:
        page_size = DEFAULT_PAGE_SIZE
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


class PaginationParams(BaseModel):
    """Validated `page` / `page_size` query parameters.

    Used as a FastAPI dependency so every list endpoint enforces the same
    limits and returns the same frozen ``10002`` code when they are exceeded,
    instead of each module inventing its own bound.
    """

    page: int = Field(default=DEFAULT_PAGE, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        """Row offset for a SQL LIMIT/OFFSET clause."""
        return (self.page - 1) * self.page_size
