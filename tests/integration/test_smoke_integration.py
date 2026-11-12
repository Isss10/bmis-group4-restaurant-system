"""Integration smoke tests: app boots, health and auth behave correctly.

Skips itself when APP_DB_HOST is unset (unit-only local runs).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("APP_DB_HOST"),
    reason="Set APP_DB_HOST to enable DB-backed integration tests.",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from src.presentation.api.main import create_app

    return TestClient(create_app())


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_root_index(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["api_base"] == "/api/v1"


def test_me_without_token_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
