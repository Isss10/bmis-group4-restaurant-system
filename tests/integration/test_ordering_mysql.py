"""Integration tests for the ordering module against real MySQL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.common.config import get_settings
from src.data.database import get_engine, get_session_factory, reset_engine
from src.data.models.dish import Dish
from src.data.models.order import Order
from src.presentation.api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_mysql() -> None:
    if not os.environ.get("APP_DB_HOST"):
        pytest.skip("Real-MySQL ordering checks require APP_DB_HOST")
    cfg = get_settings()
    if cfg.environment != "testing" or cfg.db_name != "restaurant_test":
        pytest.fail("Refusing destructive integration checks outside testing/restaurant_test")


@pytest.fixture(autouse=True)
def setup_database() -> None:
    root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(root / "src/data/migration"))

    engine = get_engine()
    from sqlalchemy import MetaData

    meta = MetaData()
    meta.reflect(bind=engine)
    meta.drop_all(bind=engine)

    command.upgrade(alembic_cfg, "head")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    app = create_app(get_settings())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed_menu() -> dict[str, int]:
    factory = get_session_factory()
    with factory() as session:
        dish1 = Dish(name="Integration Burger", price=15.5, category="food")
        dish2 = Dish(name="Integration Cola", price=5.0, category="drink")
        session.add_all([dish1, dish2])
        session.commit()
        return {"burger": dish1.id, "cola": dish2.id}


def test_customer_can_create_and_fetch_order(client: TestClient, seed_menu: dict[str, int]) -> None:
    payload = {
        "customer_name": "Integration Tester",
        "items": [
            {"dish_id": seed_menu["burger"], "quantity": 2},
            {"dish_id": seed_menu["cola"], "quantity": 1},
        ],
    }

    response = client.post("/api/v1/orders/", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]

    order_id = data["id"]
    assert data["customer_name"] == "Integration Tester"
    assert data["total_price"] == 36.0
    assert data["status"] == "pending"
    assert len(data["items"]) == 2

    fetch_response = client.get(f"/api/v1/orders/{order_id}")
    assert fetch_response.status_code == 200
    assert fetch_response.json()["data"]["id"] == order_id


def test_order_saves_price_snapshot(client: TestClient, seed_menu: dict[str, int]) -> None:
    payload = {
        "customer_name": "Snapshot Tester",
        "items": [{"dish_id": seed_menu["burger"], "quantity": 1}],
    }
    response = client.post("/api/v1/orders/", json=payload)
    assert response.status_code == 200
    order_id = response.json()["data"]["id"]

    factory = get_session_factory()
    with factory() as session:
        order = session.scalar(select(Order).where(Order.id == order_id))
        assert order is not None

        dish = session.scalar(select(Dish).where(Dish.id == seed_menu["burger"]))
        if dish:
            dish.price = 99.99
            session.commit()

    fetch_response = client.get(f"/api/v1/orders/{order_id}")
    assert fetch_response.status_code == 200
    assert fetch_response.json()["data"]["total_price"] == 15.5


def test_create_order_fails_with_invalid_dish(client: TestClient) -> None:
    payload = {
        "customer_name": "Invalid Dish Tester",
        "items": [{"dish_id": 999999, "quantity": 1}],
    }
    response = client.post("/api/v1/orders/", json=payload)
    assert response.status_code == 400
