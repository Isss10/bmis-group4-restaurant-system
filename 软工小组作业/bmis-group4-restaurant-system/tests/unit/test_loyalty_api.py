"""HTTP contract tests for `/api/v1/membership` loyalty endpoints."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.common.security import Role
from src.data.database import Base, get_db
from src.data.model_discovery import import_all_models
from src.data.schema.loyalty import MembershipTier
from src.presentation.api.main import create_app


@pytest.fixture
def loyalty_client(settings: Any) -> Generator[tuple[TestClient, Session], None, None]:
    import_all_models()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    db = factory()
    db.add_all(
        [
            MembershipTier(
                name="BRONZE",
                min_qualifying_spend=Decimal("0.00"),
                discount_rate=Decimal("0.0000"),
                is_active=True,
            ),
            MembershipTier(
                name="SILVER",
                min_qualifying_spend=Decimal("500.00"),
                discount_rate=Decimal("0.0200"),
                is_active=True,
            ),
        ]
    )
    db.commit()
    app = create_app(settings)

    def _session_override() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = _session_override
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, db
    db.close()
    engine.dispose()


def test_membership_endpoints_are_in_openapi(loyalty_client: tuple[TestClient, Session]) -> None:
    client, _ = loyalty_client
    paths = client.get("/openapi.json").json()["paths"]

    expected = {
        "/api/v1/membership/me",
        "/api/v1/membership/points",
        "/api/v1/membership/points/redeem",
        "/api/v1/membership/admin/points/adjust",
        "/api/v1/membership/admin/points/expire",
        "/api/v1/membership/tiers",
        "/api/v1/membership/coupons",
        "/api/v1/membership/coupons/issue",
        "/api/v1/membership/coupons/quote",
        "/api/v1/membership/coupons/redeem",
        "/api/v1/membership/events/orders/{order_id}/completed",
    }
    assert expected <= set(paths)
    for path in expected:
        for operation in paths[path].values():
            assert operation["x-module"] == "loyalty"
            assert operation["x-contract-id"].startswith("LOY-")
            assert operation["x-implementation-status"] == "implemented"


def test_customer_summary_requires_authentication(
    loyalty_client: tuple[TestClient, Session],
) -> None:
    client, _ = loyalty_client
    response = client.get("/api/v1/membership/me")

    assert response.status_code == 401
    assert response.json()["code"] == 30001


def test_order_completion_and_summary_flow(
    loyalty_client: tuple[TestClient, Session],
    auth_headers: Any,
) -> None:
    client, _ = loyalty_client
    completed = client.post(
        "/api/v1/membership/events/orders/order-100/completed",
        headers=auth_headers(Role.WAITER),
        json={"user_id": "1", "paid_amount": "105.00"},
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["points_awarded"] == 10

    summary = client.get(
        "/api/v1/membership/me",
        headers=auth_headers(Role.CUSTOMER),
    )
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["user_id"] == "1"
    assert data["points_balance"] == 10
    assert data["tier"]["name"] == "BRONZE"


def test_coupon_create_issue_quote_and_redeem(
    loyalty_client: tuple[TestClient, Session],
    auth_headers: Any,
) -> None:
    client, _ = loyalty_client
    manager = auth_headers(Role.MANAGER)
    customer = auth_headers(Role.CUSTOMER)
    valid_from = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    valid_until = (datetime.now(UTC) + timedelta(days=10)).isoformat()

    created = client.post(
        "/api/v1/membership/coupons",
        headers=manager,
        json={
            "code": "WELCOME10",
            "name": "Welcome 10 percent",
            "discount_type": "PERCENT",
            "discount_value": "10",
            "min_spend": "0.00",
            "stacking": "STACKABLE",
            "valid_from": valid_from,
            "valid_until": valid_until,
        },
    )
    assert created.status_code == 201
    coupon_id = created.json()["data"]["id"]

    issued = client.post(
        "/api/v1/membership/coupons/issue",
        headers=manager,
        json={"coupon_id": coupon_id, "user_id": "1"},
    )
    assert issued.status_code == 201
    user_coupon_id = issued.json()["data"]["user_coupon_id"]
    assert issued.json()["data"]["expires_at"].endswith("Z")

    quote = client.post(
        "/api/v1/membership/coupons/quote",
        headers=customer,
        json={"order_subtotal": "100.00", "user_coupon_ids": [user_coupon_id]},
    )
    assert quote.status_code == 200
    assert quote.json()["data"]["payable_total"] == "90.00"

    redeemed = client.post(
        "/api/v1/membership/coupons/redeem",
        headers=customer,
        json={
            "order_id": "order-coupon",
            "order_subtotal": "100.00",
            "user_coupon_ids": [user_coupon_id],
        },
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["data"]["duplicate"] is False

    replay = client.post(
        "/api/v1/membership/coupons/redeem",
        headers=customer,
        json={
            "order_id": "order-coupon",
            "order_subtotal": "100.00",
            "user_coupon_ids": [user_coupon_id],
        },
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["duplicate"] is True


def test_customer_cannot_call_manager_loyalty_endpoints(
    loyalty_client: tuple[TestClient, Session],
    auth_headers: Any,
) -> None:
    client, _ = loyalty_client
    response = client.post(
        "/api/v1/membership/admin/points/adjust",
        headers=auth_headers(Role.CUSTOMER),
        json={
            "user_id": "1",
            "points": 10,
            "reason": "manual",
            "idempotency_key": "attempt-1",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == 30003


def test_manager_adjustment_tier_and_expiry_endpoints(
    loyalty_client: tuple[TestClient, Session],
    auth_headers: Any,
) -> None:
    client, _ = loyalty_client
    manager = auth_headers(Role.MANAGER)
    customer = auth_headers(Role.CUSTOMER)

    tier = client.post(
        "/api/v1/membership/tiers",
        headers=manager,
        json={
            "name": "GOLD",
            "min_qualifying_spend": "2000.00",
            "discount_rate": "0.0500",
            "is_active": True,
        },
    )
    assert tier.status_code == 201
    assert tier.json()["data"]["name"] == "GOLD"

    adjusted = client.post(
        "/api/v1/membership/admin/points/adjust",
        headers=manager,
        json={
            "user_id": "1",
            "points": 25,
            "reason": "Service recovery",
            "idempotency_key": "api-adjust-1",
        },
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["data"]["points_balance"] == 25

    history = client.get(
        "/api/v1/membership/points",
        headers=customer,
        params={"page": 1, "page_size": 10},
    )
    assert history.status_code == 200
    assert history.json()["data"]["total"] == 1
    assert history.json()["data"]["items"][0]["points"] == 25

    tiers = client.get("/api/v1/membership/tiers", headers=customer)
    assert tiers.status_code == 200
    assert {item["name"] for item in tiers.json()["data"]} >= {"BRONZE", "GOLD"}

    expiry = client.post(
        "/api/v1/membership/admin/points/expire",
        headers=manager,
    )
    assert expiry.status_code == 200
    assert expiry.json()["data"] == {"expired_lots": 0, "expired_points": 0}
