"""Pure unit tests for the FR-ORD-04 order state machine.

No database and no ORM construction: these pin the frozen vocabulary, the legal
transition table and the lowercase-compatibility reader that M5's stored rows
rely on. Kept separate from the API tests so coverage of the new domain module
does not depend on SQLite or the M5 models.
"""

import pytest

from src.application.ordering.models import (
    ALLOWED_TRANSITIONS,
    OrderStatus,
    normalize_order_status,
)
from src.common.errors import ApiError, ErrorCode


def test_all_six_states_are_uppercase() -> None:
    assert [member.value for member in OrderStatus] == [
        "PENDING",
        "ACCEPTED",
        "PREPARING",
        "SERVED",
        "COMPLETED",
        "CANCELLED",
    ]


def test_legal_linear_chain_is_complete() -> None:
    assert ALLOWED_TRANSITIONS[OrderStatus.PENDING] == frozenset(
        {OrderStatus.ACCEPTED, OrderStatus.CANCELLED}
    )
    assert ALLOWED_TRANSITIONS[OrderStatus.ACCEPTED] == frozenset(
        {OrderStatus.PREPARING, OrderStatus.CANCELLED}
    )
    assert ALLOWED_TRANSITIONS[OrderStatus.PREPARING] == frozenset(
        {OrderStatus.SERVED, OrderStatus.CANCELLED}
    )
    assert ALLOWED_TRANSITIONS[OrderStatus.SERVED] == frozenset({OrderStatus.COMPLETED})


def test_completed_and_cancelled_are_terminal() -> None:
    assert ALLOWED_TRANSITIONS[OrderStatus.COMPLETED] == frozenset()
    assert ALLOWED_TRANSITIONS[OrderStatus.CANCELLED] == frozenset()


def test_illegal_jumps_are_not_in_the_table() -> None:
    assert OrderStatus.COMPLETED not in ALLOWED_TRANSITIONS[OrderStatus.PENDING]
    assert OrderStatus.ACCEPTED not in ALLOWED_TRANSITIONS[OrderStatus.COMPLETED]
    assert OrderStatus.SERVED not in ALLOWED_TRANSITIONS[OrderStatus.PENDING]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pending", OrderStatus.PENDING),
        ("PENDING", OrderStatus.PENDING),
        (" PENDING ", OrderStatus.PENDING),
        ("Accepted", OrderStatus.ACCEPTED),
        ("completed", OrderStatus.COMPLETED),
    ],
)
def test_normalize_accepts_m5_lowercase_and_legacy_values(raw: str, expected: OrderStatus) -> None:
    assert normalize_order_status(raw) is expected


def test_normalize_rejects_unknown_status_with_the_frozen_20003() -> None:
    with pytest.raises(ApiError) as exc_info:
        normalize_order_status("SEATED")

    assert exc_info.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION
    assert exc_info.value.errors is not None
    assert exc_info.value.errors[0]["field"] == "status"
