import pytest
from httpx import AsyncClient
from src.main import app


@pytest.mark.asyncio
async def test_get_menu_no_category():
    # Request menu endpoint without category filter
    async with AsyncClient(app=app, base_url="http://test") as client:
        res = await client.get("/api/v1/orders/menu")
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0
        assert isinstance(json_resp["data"], list)


@pytest.mark.asyncio
async def test_get_menu_with_category():
    # Request menu endpoint with category filter parameter
    async with AsyncClient(app=app, base_url="http://test") as client:
        res = await client.get("/api/v1/orders/menu?category=drink")
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0
        assert isinstance(json_resp["data"], list)


@pytest.mark.asyncio
async def test_submit_order():
    # Create new valid order
    payload = {
        "dish_items": [{"dish_id": 1, "quantity": 2}],
        "customer_name": "test",
        "table_no": "A01"
    }
    async with AsyncClient(app=app, base_url="http://test") as client:
        res = await client.post("/api/v1/orders/", json=payload)
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0


@pytest.mark.asyncio
async def test_submit_order_bad_data():
    # Submit invalid order payload
    payload = {"dish_items": []}
    async with AsyncClient(app=app, base_url="http://test") as client:
        res = await client.post("/api/v1/orders/", json=payload)
        assert res.status_code in (400, 422)