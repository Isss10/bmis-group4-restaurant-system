"""Tests for the HTTP layer: health endpoint, error envelope, security headers.

These assert the API *contract* that the Vue frontend depends on. If the error
shape changes, every frontend error handler breaks at once, so it is pinned
here.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.common.config import Settings
from src.common.errors import ErrorCode, slot_conflict
from src.common.middleware import register_middleware
from src.common.security import Role, require_roles
from src.presentation.api.main import create_app

# ---------------------------------------------------------------------------
# Health & root
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        assert client.get("/health").status_code == status.HTTP_200_OK

    def test_contract_health_path_also_served(self, client: TestClient) -> None:
        """Manual §4.1 mandates the `/api/v1/` prefix; Wave 1 acceptance checks it."""
        response = client.get("/api/v1/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["status"] == "ok"

    def test_alias_and_contract_path_return_the_same_payload(self, client: TestClient) -> None:
        """Two routes, one handler: they must not be able to drift apart.

        The request id and timestamp differ per call, so compare only `data`.
        """
        contract = client.get("/api/v1/health").json()["data"]
        alias = client.get("/health").json()["data"]
        assert contract == alias

    def test_health_does_not_need_the_database(self, client: TestClient) -> None:
        """Liveness must stay up while MySQL is down.

        Otherwise the orchestrator kills the API in a restart loop instead of
        recovering the database.
        """
        payload = client.get("/health").json()
        # The liveness fields live under `data` now that every endpoint returns
        # the frozen envelope (manual §4.2).
        assert payload["data"]["status"] == "ok"

    def test_health_reports_environment(self, client: TestClient) -> None:
        assert client.get("/health").json()["data"]["environment"] == "testing"

    def test_health_is_wrapped_in_the_envelope(self, client: TestClient) -> None:
        """The container HEALTHCHECK only asserts HTTP 200, so wrapping is safe."""
        payload = client.get("/health").json()
        assert payload["code"] == 0
        assert payload["message"] == "ok"
        assert set(payload) == {"code", "message", "data", "request_id", "timestamp"}

    def test_alias_is_hidden_from_the_openapi_document(self, client: TestClient) -> None:
        """Documenting two health endpoints invites the frontend to use the
        non-contract one; the alias exists for infrastructure only."""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/health" in paths
        assert "/health" not in paths

    def test_health_exposes_no_secrets(self, client: TestClient) -> None:
        """The probe is unauthenticated, so it must not echo configuration."""
        body = client.get("/health").text.lower()
        for forbidden in ("password", "secret", "mysql", "pymysql", "jwt"):
            assert forbidden not in body

    def test_root_returns_service_index(self, client: TestClient) -> None:
        payload = client.get("/").json()
        assert payload["api_base"] == "/api/v1"
        assert "version" in payload


class TestOpenApiDocumentation:
    """Objective (f) requires a documented REST API; FastAPI generates it."""

    def test_openapi_schema_is_served_in_non_production(self, client: TestClient) -> None:
        assert client.get("/openapi.json").status_code == status.HTTP_200_OK

    def test_swagger_ui_is_available_in_non_production(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == status.HTTP_200_OK

    def test_openapi_declares_bearer_auth(self, client: TestClient) -> None:
        """The generated docs must show that endpoints need a JWT."""
        schema = client.get("/openapi.json").json()
        schemes = schema.get("components", {}).get("securitySchemes", {})
        assert any(
            value.get("type") == "http" and value.get("scheme") == "bearer"
            for value in schemes.values()
        ), "no bearer security scheme in the OpenAPI document"

    def test_docs_are_disabled_in_production(self) -> None:
        """An interactive API console must not be public on a live system."""
        production = Settings(
            environment="production",
            jwt_secret_key="a-genuinely-long-and-unique-production-secret-value",
            db_password="a-genuinely-unique-production-db-password",
            cors_origins="https://restaurant.example.com",
        )
        with TestClient(create_app(production)) as production_client:
            assert production_client.get("/docs").status_code == status.HTTP_404_NOT_FOUND
            assert production_client.get("/openapi.json").status_code == status.HTTP_404_NOT_FOUND
            # Health stays reachable — the orchestrator still needs it.
            assert production_client.get("/health").status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ],
    )
    def test_hardening_headers_on_every_response(
        self, client: TestClient, header: str, expected: str
    ) -> None:
        assert client.get("/health").headers[header] == expected

    def test_permissions_policy_disables_unused_browser_features(self, client: TestClient) -> None:
        assert "geolocation=()" in client.get("/health").headers["Permissions-Policy"]

    def test_request_id_is_returned_to_the_client(self, client: TestClient) -> None:
        """Support needs this id to find the matching server log line."""
        request_id = client.get("/health").headers["X-Request-ID"]
        assert len(request_id) >= 16

    def test_request_ids_differ_between_requests(self, client: TestClient) -> None:
        first = client.get("/health").headers["X-Request-ID"]
        second = client.get("/health").headers["X-Request-ID"]
        assert first != second

    def test_inbound_request_id_is_preserved(self, client: TestClient) -> None:
        """A reverse proxy's id must survive so logs correlate end-to-end."""
        forwarded = "a" * 32
        assert (
            client.get("/health", headers={"X-Request-ID": forwarded}).headers["X-Request-ID"]
            == forwarded
        )

    @pytest.mark.parametrize(
        "malicious",
        [
            "short",
            "x" * 200,
            "has spaces in it",
            "line\r\nbreak",
            "new\nline",
            "semi;colon",
            "",
        ],
    )
    def test_unsafe_inbound_request_id_is_replaced(
        self, client: TestClient, malicious: str
    ) -> None:
        """An unvalidated header echoed back enables log injection and header splitting."""
        returned = client.get("/health", headers={"X-Request-ID": malicious}).headers[
            "X-Request-ID"
        ]
        assert returned != malicious or malicious == ""
        assert all(character.isalnum() or character in "-_" for character in returned)

    def test_hsts_absent_in_development(self, client: TestClient) -> None:
        """Pinning HSTS on a plain-HTTP dev server would break local access."""
        assert "Strict-Transport-Security" not in client.get("/health").headers

    def test_csp_and_hsts_present_in_production(self) -> None:
        production = Settings(
            environment="production",
            jwt_secret_key="a-genuinely-long-and-unique-production-secret-value",
            db_password="a-genuinely-unique-production-db-password",
            cors_origins="https://restaurant.example.com",
        )
        with TestClient(create_app(production)) as production_client:
            headers = production_client.get("/health").headers
            assert "max-age=31536000" in headers["Strict-Transport-Security"]
            assert "default-src 'self'" in headers["Content-Security-Policy"]


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


@pytest.fixture
def probe_app() -> FastAPI:
    """A minimal app with routes that raise each class of error."""
    app = FastAPI()
    register_middleware(app, Settings(environment="testing"))

    @app.get("/boom")
    async def boom() -> None:
        msg = "simulated internal failure with sensitive detail: db=pw123"
        raise RuntimeError(msg)

    @app.get("/denied")
    async def denied() -> None:
        raise HTTPException(status_code=403, detail="Forbidden by policy")

    @app.get("/echo")
    async def echo(missing: str) -> dict[str, Any]:
        return {"missing": missing}

    @app.get("/conflict")
    async def conflict() -> None:
        """Raise the domain error that is this project's concurrency evidence.

        The reservation service raises exactly this when the unique-constraint
        safety net fires, so the envelope it produces is contract-critical: the
        frontend and the concurrency acceptance test both key on code 20001.
        """
        raise slot_conflict("conflict with reservation #1024")

    return app


@pytest.fixture
def probe_client(probe_app: FastAPI) -> TestClient:
    return TestClient(probe_app, raise_server_exceptions=False)


class TestErrorEnvelope:
    """The frozen envelope from manual §4.2.

    Shape on failure: a FLAT object with these keys —
    ``code``, ``message``, ``data`` (null), ``errors`` (omitted when there is no
    field-level detail), ``request_id`` and ``timestamp``.
    There is deliberately no outer ``{"error": {...}}`` wrapper — the earlier
    nested shape is what the contract replaced, and these tests are the thing
    that stops it creeping back.
    """

    def test_unhandled_error_returns_the_internal_code(self, probe_client: TestClient) -> None:
        payload = probe_client.get("/boom").json()
        # 50001, not the bare HTTP 500: the body carries the frozen business code.
        assert payload["code"] == int(ErrorCode.INTERNAL_ERROR)
        assert payload["message"] == "服务器内部错误"
        assert payload["data"] is None
        assert "request_id" in payload
        assert "timestamp" in payload

    def test_unhandled_error_does_not_leak_internals(self, probe_client: TestClient) -> None:
        """Exception text routinely contains SQL, paths and credentials (OWASP A05)."""
        body = probe_client.get("/boom").text
        assert "pw123" not in body
        assert "RuntimeError" not in body
        assert "Traceback" not in body

    def test_envelope_has_no_legacy_error_wrapper(self, probe_client: TestClient) -> None:
        """Pin the flat shape: a top-level "error" key means someone reverted it."""
        payload = probe_client.get("/boom").json()
        assert "error" not in payload
        assert set(payload) == {"code", "message", "data", "request_id", "timestamp"}

    def test_timestamp_is_iso8601_utc_with_z(self, probe_client: TestClient) -> None:
        """The frontend parses this string; the contract fixes it to a `Z` suffix."""
        ts = probe_client.get("/boom").json()["timestamp"]
        assert ts.endswith("Z")
        assert "+" not in ts  # not the `+00:00` spelling
        from datetime import datetime

        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")  # raises if malformed

    def test_bare_http_exception_maps_to_a_frozen_code(self, probe_client: TestClient) -> None:
        response = probe_client.get("/denied")
        assert response.status_code == 403
        # A bare HTTPException(403) has no business code, so the middleware maps
        # it onto the frozen 30003 rather than echoing the HTTP number.
        assert response.json()["code"] == int(ErrorCode.PERMISSION_DENIED)

    def test_domain_error_carries_its_business_code(self, probe_client: TestClient) -> None:
        """The concurrency-evidence path: ApiError(20001) must survive to the client."""
        response = probe_client.get("/conflict")
        assert response.status_code == 409
        payload = response.json()
        assert payload["code"] == int(ErrorCode.SLOT_ALREADY_BOOKED)
        assert payload["message"] == "该时段该餐桌已被预订"

    def test_domain_error_includes_field_level_detail(self, probe_client: TestClient) -> None:
        payload = probe_client.get("/conflict").json()
        errors = payload["errors"]
        assert any(e["field"] == "slot_id" for e in errors)
        assert any("reservation #1024" in e["detail"] for e in errors)

    def test_validation_error_uses_the_validation_code(self, probe_client: TestClient) -> None:
        """A missing required query param is 10001, not a bare 422."""
        response = probe_client.get("/echo")
        # Literal 422 rather than status.HTTP_422_UNPROCESSABLE_ENTITY: starlette
        # deprecated that constant name in 1.7 (renamed to
        # HTTP_422_UNPROCESSABLE_CONTENT) and this suite treats warnings as
        # errors. See the matching note in src/common/middleware.py.
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == int(ErrorCode.VALIDATION_FAILED)

    def test_validation_error_lists_the_offending_field(self, probe_client: TestClient) -> None:
        """The frontend needs to know *which* field to highlight."""
        payload = probe_client.get("/echo").json()
        fields = payload["errors"]
        assert any(field["field"] == "missing" for field in fields)

    def test_validation_error_uses_contract_detail_key(self, probe_client: TestClient) -> None:
        """Manual §4.2 names the key `detail`, not `message` — easy to get wrong."""
        field = probe_client.get("/echo").json()["errors"][0]
        assert "detail" in field
        assert "message" not in field

    def test_validation_error_drops_the_body_marker(self, probe_client: TestClient) -> None:
        """`body.missing` is noise to a client; the field name alone is enough."""
        fields = probe_client.get("/echo").json()["errors"]
        assert all(not field["field"].startswith("body.") for field in fields)

    def test_errors_key_absent_when_no_field_detail(self, probe_client: TestClient) -> None:
        """A 500 has no field-level detail; `errors` must be omitted, not `[]`.

        This lets the client distinguish "no fields to highlight" from "these
        specific fields are wrong" by key presence.
        """
        payload = probe_client.get("/boom").json()
        assert "errors" not in payload

    def test_error_response_carries_a_request_id_header(self, probe_client: TestClient) -> None:
        response = probe_client.get("/boom")
        header_id = response.headers["X-Request-ID"]
        body_id = response.json()["request_id"]
        assert header_id == body_id

    def test_unknown_route_returns_the_envelope(self, client: TestClient) -> None:
        response = client.get("/no-such-endpoint")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        payload = response.json()
        assert payload["code"] == int(ErrorCode.RESOURCE_NOT_FOUND)
        assert "request_id" in payload


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCors:
    def test_allowlisted_origin_is_permitted(self, client: TestClient) -> None:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"

    def test_unlisted_origin_is_not_permitted(self, client: TestClient) -> None:
        """Without this, any website could call the API with a stolen token."""
        response = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"

    def test_wildcard_cors_is_refused_in_production(self) -> None:
        """The single most dangerous CORS misconfiguration.

        Two independent guards exist, and this asserts on the first one. The
        config validator refuses to *construct* production settings containing a
        wildcard, so `Settings(...)` raises before `create_app` is ever reached.
        That is the guard a normal deployment hits.
        """
        with pytest.raises(ValidationError, match=r"must not contain '\*'"):
            Settings(
                environment="production",
                jwt_secret_key="a-genuinely-long-and-unique-production-secret-value",
                db_password="a-genuinely-unique-production-db-password",
                cors_origins="*",
            )

    def test_middleware_guard_is_the_second_line_of_defence(self) -> None:
        """The middleware check is reachable, and is not dead code.

        `Settings.model_copy(update=...)` bypasses validation — a pattern used
        elsewhere in this suite to inject a deliberately broken setting. If
        anything ever produces production settings with a wildcard that way,
        `register_middleware` must still refuse rather than silently serving
        `Access-Control-Allow-Origin: *` with credentials.
        """
        unsafe = Settings(
            environment="development",
            jwt_secret_key="a-genuinely-long-and-unique-production-secret-value",
            db_password="a-genuinely-unique-production-db-password",
            cors_origins="*",
        ).model_copy(update={"environment": "production"})

        # Confirm the bypass really happened: the value survived validation.
        assert unsafe.environment == "production"
        assert "*" in unsafe.cors_origin_list

        app = FastAPI()
        with pytest.raises(RuntimeError, match=r"must not contain '\*'"):
            register_middleware(app, unsafe)

    def test_wildcard_is_still_allowed_outside_production(self) -> None:
        """Local development with `*` must keep working.

        The guard targets production only. Blocking `*` in development would
        just push people to disable the check entirely.
        """
        app = create_app(
            Settings(environment="development", cors_origins="*"),
        )
        assert "*" in app.state.settings.cors_origin_list


# ---------------------------------------------------------------------------
# Role guards end to end
# ---------------------------------------------------------------------------


@pytest.fixture
def guarded_app() -> FastAPI:
    """An app with one manager-only route, to test the guard wiring."""
    app = FastAPI()
    register_middleware(app, Settings(environment="testing"))

    @app.get("/manager-only", dependencies=[Depends(require_roles(Role.MANAGER, Role.ADMIN))])
    async def manager_only() -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.fixture
def guarded_client(guarded_app: FastAPI) -> TestClient:
    return TestClient(guarded_app, raise_server_exceptions=False)


class TestRoleGuards:
    def test_manager_is_permitted(self, guarded_client: TestClient, auth_headers: Any) -> None:
        response = guarded_client.get("/manager-only", headers=auth_headers(Role.MANAGER))
        assert response.status_code == status.HTTP_200_OK

    def test_customer_is_rejected_with_403(
        self, guarded_client: TestClient, auth_headers: Any
    ) -> None:
        """403 not 401: the caller IS authenticated, just not permitted."""
        response = guarded_client.get("/manager-only", headers=auth_headers(Role.CUSTOMER))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_waiter_cannot_reach_manager_endpoints(
        self, guarded_client: TestClient, auth_headers: Any
    ) -> None:
        """A01 Broken Access Control — the top OWASP risk for this project."""
        response = guarded_client.get("/manager-only", headers=auth_headers(Role.WAITER))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_token_is_rejected_with_401(self, guarded_client: TestClient) -> None:
        response = guarded_client.get("/manager-only")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_malformed_token_is_rejected_with_401(self, guarded_client: TestClient) -> None:
        response = guarded_client.get(
            "/manager-only", headers={"Authorization": "Bearer not.a.real.token"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_forged_admin_token_is_rejected(self, guarded_client: TestClient) -> None:
        """A token signed with the wrong secret must not grant access."""
        forged = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxIiwicm9sZSI6ImFkbWluIiwiZXhwIjo5OTk5OTk5OTk5fQ."
            "invalid-signature"
        )
        response = guarded_client.get(
            "/manager-only", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_403_body_does_not_reveal_which_roles_are_allowed(
        self, guarded_client: TestClient, auth_headers: Any
    ) -> None:
        """Telling an attacker the required role hands them a target."""
        body = guarded_client.get("/manager-only", headers=auth_headers(Role.CUSTOMER)).text.lower()
        assert "manager" not in body
        assert "admin" not in body
