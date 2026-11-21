"""Order state machine (FR-ORD-04). Purely additive to the ordering module.

M5 shipped with status stored as ad-hoc lowercase strings. This module freezes
the uppercase vocabulary and the legal transitions; the staff back-office
consumes it through OrderingService, never by reading the orders table
directly (docs/design/ARCHITECTURE.md §7).
"""

from __future__ import annotations

import enum

from src.common.errors import illegal_transition


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    SERVED = "SERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.ACCEPTED, OrderStatus.CANCELLED}),
    OrderStatus.ACCEPTED: frozenset({OrderStatus.PREPARING, OrderStatus.CANCELLED}),
    OrderStatus.PREPARING: frozenset({OrderStatus.SERVED, OrderStatus.CANCELLED}),
    OrderStatus.SERVED: frozenset({OrderStatus.COMPLETED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def normalize_order_status(raw: str) -> OrderStatus:
    """Read M5's lowercase 'pending' (and any legacy value) as an OrderStatus."""
    try:
        return OrderStatus(str(raw).strip().upper())
    except ValueError as exc:
        raise illegal_transition(f"unrecognised stored status: {raw!r}") from exc
