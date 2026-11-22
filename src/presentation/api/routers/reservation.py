"""HTTP surface for the reservation module (Objective a).

Mounted by the loader at the frozen base path ``/api/v1/reservations`` (manual
§4.2). No internal prefix here — the loader supplies it, and a second prefix in
this file produced double-prefixed routes in an earlier revision.

Layering (§3)
-------------
This file knows HTTP and nothing else. Every business rule — the state machine,
the hold TTL, which slots exist, who may touch a row — lives in
:class:`~src.application.reservation.service.ReservationService`. The service
raises :class:`ApiError`; the global handler registered in ``common/middleware``
turns it into the frozen envelope with the right status code. No ``try/except``
here maps domain errors, because that mapping is the handler's job and
duplicating it per-router is how two routers end up disagreeing.

Identity (§7, OWASP A01)
------------------------
The acting user is **always** taken from the verified token (``identity.sub``),
never from the request body. A client-supplied ``user_id`` is accepted only to
be *rejected* when it disagrees with the token — that is what
``test_customer_cannot_create_booking_for_another_identity`` asserts, and it is
the difference between "a customer books a table" and "a customer books or
cancels on behalf of anyone".

Status casing — a known inconsistency, deliberately preserved
-------------------------------------------------------------
This router emits status values **lowercase** (``"held"``, ``"cancelled"``); the
staff router emits them **uppercase** (``"HELD"``). That is not a decision made
here — it is the contract each router's existing consumers already assert
(``test_membership_authorization`` expects ``"cancelled"``, ``test_staff_api``
expects ``"PENDING"``). Changing either would break another member's test suite,
so unifying it belongs in a contract PR with all three frontend owners present
(ARCHITECTURE.md §6, REST API contract — owner YAN ZHANG). Flagged, not silently
fixed.
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.application.reservation.models import ReservationStatus
from src.application.reservation.repository import AuditContext
from src.application.reservation.service import (
    DEFAULT_PARTY_SIZE,
    OPENING_HOUR,
    SLOT_MINUTES,
    ReservationService,
)
from src.common.envelope import success
from src.common.errors import permission_denied
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import Role, TokenPayload, require_roles, require_staff

router = APIRouter(tags=["reservation"])
service = ReservationService()

Customer = Annotated[TokenPayload, Depends(require_roles(Role.CUSTOMER))]
Staff = Annotated[TokenPayload, Depends(require_staff())]

# Every authenticated role. `require_roles(*Role)` unpacks the enum's members, so
# the four role names are listed exactly once, here. Hoisted to a module-level
# singleton because B008 forbids calling `Depends()` in an argument default, and
# because the two read endpoints must not be able to drift apart on who may call
# them — both scope by role *inside* the handler instead.
AnyUser = Annotated[TokenPayload, Depends(require_roles(*Role))]

# Likewise for the availability query parameter, so the OpenAPI description is
# declared once rather than repeated per endpoint.
SlotDateQuery = Annotated[date, Query(description="Date to check, e.g. 2026-12-01.")]

# Maximum party size the prototype accepts. Not a business rule from the
# contract — there is no table-capacity catalog to validate against yet (see
# DEFAULT_TABLE_IDS in the service) — so this is a sanity bound that keeps a
# malformed request from writing an absurd number, and it is validated by the
# service's grid check rather than only here.
_MAX_PARTY_SIZE = 20


class BookingSchema(BaseModel):
    """A request to hold one table for one discrete slot (FR-RES-02/03).

    The slot is discrete — a date plus a grid-aligned start — because only a
    discrete key can back the §5.3 unique constraint that makes the concurrency
    guarantee real. A free-form start/end range cannot be made unique in MySQL,
    which is why the earlier ``reservation_time`` shape was replaced.
    """

    table_id: int = Field(gt=0, description="Numeric table identifier.")
    slot_date: date = Field(description="Booking date, e.g. 2026-12-01.")
    slot_start: time = Field(
        description=(
            f"Slot start on the frozen {SLOT_MINUTES}-minute grid, "
            f"{OPENING_HOUR:02d}:00 onwards, e.g. 19:30:00."
        )
    )
    party_size: int = Field(
        default=DEFAULT_PARTY_SIZE, ge=1, le=_MAX_PARTY_SIZE, description="Guests in the party."
    )
    user_id: str | None = Field(
        default=None,
        description=(
            "Deprecated legacy field. Ownership is derived from the token; a value "
            "here that disagrees with the token is rejected with 30003."
        ),
    )


class StatusUpdateSchema(BaseModel):
    """Body for the back-office status patch (FR-RES-06)."""

    status: ReservationStatus = Field(
        description="Target state from the seven-state vocabulary (uppercase)."
    )


def _request_id(request: Request) -> str | None:
    """The correlation id this request was assigned by the middleware."""
    return getattr(request.state, REQUEST_ID_ATTR, None)


def _audit(request: Request, identity: TokenPayload | None) -> AuditContext:
    """Build the audit context for a write (FR-RES-08).

    ``identity`` may be ``None`` for a system-triggered sweep; ``record_audit``
    then stores NULL for the actor, which is how "the system did this" is
    distinguished from "someone did this" in the audit trail.
    """
    client = request.client
    return AuditContext(
        actor_id=identity.sub if identity else None,
        actor_role=str(identity.role) if identity else None,
        request_id=_request_id(request),
        ip_address=client.host if client else None,
        user_agent=request.headers.get("user-agent"),
    )


def _serialise(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one reservation for this router's response contract.

    Status is lowercased (see the module docstring: this router's consumers
    already assert lowercase, and the staff router's assert uppercase). Dates and
    times are rendered as ISO strings rather than left to the encoder so the
    customer-facing and staff-facing payloads use the same spellings for the same
    values — ``2026-12-01`` and ``19:30:00`` — instead of one router emitting
    ``19:30`` and the other ``19:30:00``.
    """
    out = dict(row)
    status = out.get("status")
    if status is not None:
        out["status"] = status.value.lower() if hasattr(status, "value") else str(status).lower()
    # `isinstance(..., date)` also matches `datetime` (a subclass), so datetimes
    # render with their time part and plain dates do not — which is what both
    # spellings need. mypy cannot narrow through `hasattr`, hence the explicit
    # check.
    for key in ("slot_date", "created_at", "updated_at", "expires_at"):
        value = out.get(key)
        if isinstance(value, date):
            out[key] = value.isoformat()
    slot_start = out.get("slot_start")
    if isinstance(slot_start, time):
        out["slot_start"] = slot_start.isoformat(timespec="seconds")
    return out


def _reject_foreign_identity(payload_user_id: str | None, identity: TokenPayload) -> None:
    """Refuse a body that claims a different user than the token (OWASP A01)."""
    if payload_user_id is not None and payload_user_id != identity.sub:
        raise permission_denied()


# --- availability ----------------------------------------------------------
# Declared before the parameterised routes: FastAPI matches in declaration order,
# and a literal path declared after `/{reservation_id}` would be shadowed.
@router.get("/availability", summary="Free slots per table for one date")
def get_availability(
    request: Request,
    _identity: Customer,
    slot_date: SlotDateQuery,
) -> dict[str, Any]:
    """Which tables still have a free slot on ``slot_date`` (FR-RES-01).

    An expired hold does not occupy a slot, so availability stays correct even if
    the expiry sweep has never run (FR-RES-04).

    ``table_label``, ``seats`` and ``zone`` are **not** returned: the schema has
    no dining-table catalog to read them from. Clients must not expect those
    fields until that table exists (see ``DEFAULT_TABLE_IDS`` in the service).
    """
    data = service.availability(slot_date)
    return success(data, request_id=_request_id(request))


@router.post("/expire-holds", summary="Sweep lapsed holds to EXPIRED")
def expire_holds(request: Request, _identity: Staff) -> dict[str, Any]:
    """Expire every hold whose TTL has passed (FR-RES-04).

    Staff-only: it is an operational action that frees slots, and a customer
    could otherwise clear a rival's hold. The same domain method backs any
    scheduled job, so there is exactly one expiry implementation to keep correct.
    """
    expired = service.expire_holds(audit=_audit(request, _identity))
    return success(
        {"expired_count": expired},
        message="Expired holds released",
        request_id=_request_id(request),
    )


# --- booking ---------------------------------------------------------------
def _book(payload: BookingSchema, request: Request, identity: TokenPayload) -> dict[str, Any]:
    """Shared handler for the two create shapes (see the ``/book`` alias)."""
    _reject_foreign_identity(payload.user_id, identity)

    created = service.create_reservation(
        user_id=identity.sub,
        table_id=payload.table_id,
        slot_date=payload.slot_date,
        slot_start=payload.slot_start,
        party_size=payload.party_size,
        audit=_audit(request, identity),
    )
    return success(
        _serialise(created),
        message="Reservation held",
        request_id=_request_id(request),
    )


@router.post("", summary="Create a reservation (holds the slot)")
def create_reservation(
    payload: BookingSchema, request: Request, identity: Customer
) -> dict[str, Any]:
    """Create a ``HELD`` reservation for one slot (FR-RES-02).

    The row starts ``HELD`` with ``expires_at = now + seat_hold_ttl_seconds`` and
    becomes ``CONFIRMED`` only on an explicit ``POST /{id}/confirm`` — a hold is
    never implicitly confirmed, and an unconfirmed one expires.

    Concurrent bookings for the same table and slot produce exactly one row: the
    loser gets ``code 20001`` from the §5.3 unique constraint (FR-RES-03).
    """
    return _book(payload, request, identity)


@router.post("/book", summary="Create a reservation (alias)")
def book_reservation(
    payload: BookingSchema, request: Request, identity: Customer
) -> dict[str, Any]:
    """Alias of ``POST /api/v1/reservations`` with an explicit verb.

    Exists because ``tests/concurrency/test_concurrent_booking.py`` — the
    Objective (d) acceptance test owned by M4/M7 — posts to this path. Two
    spellings of one operation is API surface nobody wants; unifying them needs
    the concurrency suite's owners to move to one path, so the alias is kept and
    flagged rather than quietly dropped. Both share ``_book``, so they cannot
    drift in behaviour.
    """
    return _book(payload, request, identity)


# --- customer actions ------------------------------------------------------
@router.get("", summary="List reservations")
def list_reservations(request: Request, identity: AnyUser) -> dict[str, Any]:
    """Staff see every reservation; a customer sees only their own (FR-RES-06).

    The role is read from the token, never from a query parameter — a customer
    must not be able to ask for the full list by adding one.
    """
    scope = None if identity.role.is_staff else identity.sub
    rows = service.list_reservations(user_id=scope)
    return success(
        [_serialise(row) for row in rows],
        request_id=_request_id(request),
    )


@router.get("/{reservation_id}", summary="Get one reservation")
def get_reservation(
    reservation_id: int,
    request: Request,
    identity: AnyUser,
) -> dict[str, Any]:
    """One reservation; a customer may only fetch their own."""
    scope = None if identity.role.is_staff else identity.sub
    row = service.get_reservation(reservation_id, user_id=scope)
    return success(_serialise(row), request_id=_request_id(request))


@router.post("/{reservation_id}/confirm", summary="Confirm a held reservation")
def confirm_reservation(
    reservation_id: int, request: Request, identity: Customer
) -> dict[str, Any]:
    """``HELD -> CONFIRMED`` on explicit customer action (FR-RES-02).

    Returns ``code 20002`` if the hold already lapsed: the slot has been released
    and may already belong to someone else, so confirming it would be an
    overbooking.
    """
    row = service.confirm(
        reservation_id,
        user_id=identity.sub,
        audit=_audit(request, identity),
    )
    return success(
        _serialise(row), message="Reservation confirmed", request_id=_request_id(request)
    )


@router.post("/{reservation_id}/cancel", summary="Cancel a reservation")
def cancel_reservation(reservation_id: int, request: Request, identity: Customer) -> dict[str, Any]:
    """Cancel one's own ``HELD`` or ``CONFIRMED`` booking (RESV-05).

    A ``SEATED`` booking is not cancellable: the guest is already at the table,
    and the state machine rejects it with 20003 rather than this route special
    casing it.
    """
    row = service.cancel(
        reservation_id,
        user_id=identity.sub,
        audit=_audit(request, identity),
    )
    return success(
        _serialise(row), message="Reservation cancelled", request_id=_request_id(request)
    )


# --- back office -----------------------------------------------------------
@router.patch("/{reservation_id}/status", summary="Set a reservation's status")
def set_status(
    reservation_id: int,
    payload: StatusUpdateSchema,
    request: Request,
    identity: Staff,
) -> dict[str, Any]:
    """Move a reservation to any legal state (FR-RES-05/06).

    Staff-only. An illegal transition — ``COMPLETED -> SEATED``, or anything out
    of a terminal state — returns ``code 20003`` whatever the request says; the
    state machine, not this route, decides.

    ``EXPIRED`` is not reachable here: it is produced only by the expiry sweep, so
    freeing a slot by voiding a hold always shows up in the audit trail as an
    expiry rather than as a routine status change.

    This overlaps ``PATCH /api/v1/staff/reservations/{id}`` (M3's route), which
    calls the same service method. Both are kept because the staff frontend is
    already wired to its own path; see the module docstring on contract drift.
    """
    row = service.set_reservation_status(
        reservation_id,
        payload.status,
        audit=_audit(request, identity),
    )
    return success(
        _serialise(row), message="Reservation status updated", request_id=_request_id(request)
    )
