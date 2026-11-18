from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.presentation.api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_menu_no_category(client: TestClient):
    with patch("src.presentation.api.routers.ordering.OrderingService") as MockService:
        instance = MockService.return_value
        instance.get_menu = AsyncMock(return_value=[])
        res = client.get("/api/v1/orders/menu")
        assert res.status_code == 200
        assert res.json()["code"] == 0


def test_get_menu_with_category(client: TestClient):
    with patch("src.presentation.api.routers.ordering.OrderingService") as MockService:
        instance = MockService.return_value
        instance.get_menu = AsyncMock(return_value=[])
        res = client.get("/api/v1/orders/menu?category=drink")
        assert res.status_code == 200
        assert res.json()["code"] == 0


def test_submit_order(client: TestClient):
    with patch("src.presentation.api.routers.ordering.OrderingService") as MockService:
        instance = MockService.return_value
        instance.submit_order = AsyncMock(return_value={
            "id": 1,
            "customer_name": "test",
            "total_price": 10.0,
            "status": "pending",
            "items": []
        })
        payload = {"items": [{"dish_id": 1, "quantity": 2}], "customer_name": "test"}
        res = client.post("/api/v1/orders/", json=payload)
        assert res.status_code == 200
        assert res.json()["code"] == 0