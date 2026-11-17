"""Reserved module endpoints must fail explicitly rather than return mock data."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.common.security import Role


@pytest.mark.parametrize(
    ("method", "path", "role", "body"),
    [
        ("GET", "/api/v1/orders/menu", Role.CUSTOMER, None),
        ("POST", "/api/v1/orders", Role.CUSTOMER, {}),
        ("GET", "/api/v1/analytics/summary", Role.MANAGER, None),
        ("GET", "/api/v1/reservations/availability", Role.CUSTOMER, None),
        ("GET", "/api/v1/reviews/moderation", Role.WAITER, None),
        ("GET", "/api/v1/staff/orders", Role.WAITER, None),
        ("POST", "/api/v1/auth/register", None, {}),
        ("POST", "/api/v1/auth/login", None, {}),
        ("POST", "/api/v1/users", Role.ADMIN, {}),
        ("PATCH", "/api/v1/users/member/role", Role.ADMIN, {}),
    ],
)
def test_reserved_endpoint_returns_explicit_501(
    client: TestClient,
    auth_headers: Any,
    method: str,
    path: str,
    role: Role | None,
    body: dict | None,
) -> None:
    headers = auth_headers(role) if role is not None else None
    response = client.request(
        method,
        path,
        headers=headers,
        json=body,
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["code"] == 50001
    assert "reserved but not implemented" in payload["message"]
    assert payload["request_id"] == response.headers["X-Request-ID"]


def test_reserved_operations_are_marked_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    reserved = []
    for path, operations in paths.items():
        for method, operation in operations.items():
            if operation.get("x-implementation-status") == "reserved":
                reserved.append((method, path, operation))

    assert reserved
    assert all(operation.get("x-requirement") for _, _, operation in reserved)
    assert all("501" in operation.get("responses", {}) for _, _, operation in reserved)
