import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="function")
async def app():
    from src.presentation.api.main import app as real_app
    yield real_app

@pytest.mark.asyncio
async def test_get_menu_no_category(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/orders/menu")
        print("\n==== test_get_menu_no_category 响应 ====")
        print(res.json())
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0
        assert isinstance(json_resp["data"], list)

@pytest.mark.asyncio
async def test_get_menu_with_category(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/orders/menu?category=drink")
        print("\n==== test_get_menu_with_category 响应 ====")
        print(res.json())
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0
        assert isinstance(json_resp["data"], list)

@pytest.mark.asyncio
async def test_submit_order(app):
    payload = {
        "items": [{"dish_id": 1, "quantity": 2}],
        "customer_name": "test"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/orders/", json=payload)
        assert res.status_code == 200
        json_resp = res.json()
        assert json_resp["code"] == 0

@pytest.mark.asyncio
async def test_submit_order_bad_data(app):
    payload = {"dish_items": []}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/orders/", json=payload)
        assert res.status_code in (400, 422)
