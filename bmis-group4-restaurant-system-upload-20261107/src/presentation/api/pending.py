"""Helpers for endpoints whose routes are reserved but implementation is pending."""

from __future__ import annotations

from typing import Any, NoReturn

from src.common.errors import ApiError, ErrorCode

HTTP_NOT_IMPLEMENTED = 501
RESERVED_RESPONSES: dict[int | str, dict[str, Any]] = {
    HTTP_NOT_IMPLEMENTED: {"description": "Reserved endpoint; implementation is pending."}
}


def pending_endpoint(feature: str) -> NoReturn:
    """Reject a reserved endpoint explicitly instead of returning mock success data."""
    raise ApiError(
        ErrorCode.INTERNAL_ERROR,
        message=f"{feature} endpoint is reserved but not implemented.",
        http_status=HTTP_NOT_IMPLEMENTED,
    )


def reserved_contract(requirement: str) -> dict[str, Any]:
    """OpenAPI marker consumed by frontend and integration tooling."""
    return {
        "x-implementation-status": "reserved",
        "x-requirement": requirement,
    }
