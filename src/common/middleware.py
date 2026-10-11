"""Cross-cutting HTTP middleware: request IDs, security headers, error bodies.

Implements several OWASP Top 10 controls at the framework layer so that no
route can forget them:

* **A01 Broken Access Control** — CORS is restricted to an explicit origin
  allow-list; wildcards are refused in production.
* **A05 Security Misconfiguration** — hardened response headers
  (``X-Content-Type-Options: nosniff``, ``X-Frame-Options: DENY``,
  ``Referrer-Policy``, and a strict CSP in production).
* **A09 Logging Failures** — every request gets a correlation id that appears
  in the response header, the application log and any audit row.
* **Information disclosure** — unhandled exceptions become a generic 500 body.
  The traceback goes to the server log, never to the client.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.common.config import Settings, get_settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_ATTR = "request_id"

# HTTP 422. Spelled as a literal rather than `status.HTTP_422_UNPROCESSABLE_ENTITY`
# because starlette deprecated that constant name in 1.7 in favour of
# `HTTP_422_UNPROCESSABLE_CONTENT`. This project runs pytest with
# `filterwarnings = ["error"]`, so touching the old name fails the whole suite,
# while the new name does not exist on the older starlette pinned in
# requirements.txt. The numeric code is the contract the frontend depends on;
# only the constant's *name* changed upstream.
_UNPROCESSABLE_CONTENT = 422


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id and log the request lifecycle.

    The id is accepted from an inbound ``X-Request-ID`` header when present
    (so a reverse proxy's id is preserved end-to-end) but is length- and
    charset-validated first: an unvalidated header echoed back into logs and
    responses is a log-injection and header-splitting vector.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = self._extract_or_create(request)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log with the request id so the failure is findable, then let the
            # exception handler produce the client-facing body.
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "Unhandled error on %s %s after %.1fms",
                request.method,
                request.url.path,
                elapsed_ms,
                extra={REQUEST_ID_ATTR: request_id},
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        self._apply_security_headers(response, request.app.state.settings)

        # 4xx/5xx are logged at WARNING with timing; everything else at INFO.
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "%s %s -> %d in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={REQUEST_ID_ATTR: request_id},
        )
        return response

    @staticmethod
    def _extract_or_create(request: Request) -> str:
        """Reuse a valid inbound request id, otherwise generate one."""
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        if inbound and _is_safe_request_id(inbound):
            return inbound
        return uuid.uuid4().hex

    @staticmethod
    def _apply_security_headers(response: Response, settings: Settings) -> None:
        """Add hardening headers to every response."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        response.headers.setdefault("X-XSS-Protection", "0")
        # HSTS only over real HTTPS. Sending it on a local HTTP dev server
        # would pin the browser to HTTPS for a domain that has none.
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'",
            )
        # Do not advertise the framework and version.
        #
        # NOTE: starlette's MutableHeaders is a mapping *view* over the raw
        # header list. It implements `__delitem__` and `update`, but it has no
        # `pop()` — calling one raises AttributeError and turns every single
        # response into a 500. Check membership first, then delete.
        if "Server" in response.headers:
            del response.headers["Server"]


def _is_safe_request_id(value: str) -> bool:
    """Validate an inbound correlation id before trusting it.

    Restricting to a conservative alphanumeric charset with a length cap blocks
    CR/LF injection into headers and control characters into log files.
    """
    if not (16 <= len(value) <= 64):
        return False
    return all(c.isalnum() or c in "-_" for c in value)


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record.

    Makes ``%(request_id)s`` usable in the log formatter so all lines produced
    while handling one request can be grepped together.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, REQUEST_ID_ATTR):
            setattr(record, REQUEST_ID_ATTR, "-")
        return True


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def _error_response(
    request: Request,
    status_code: int,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build a uniform error body.

    Shape: ``{"error": {"code": ..., "message": ..., "request_id": ...}}``.
    A single consistent shape means the Vue frontend has one error-handling
    path instead of special-casing every endpoint.

    ``headers`` are merged in *before* the correlation id so an exception's own
    headers survive the rebuild — see ``http_exception_handler``.

    Typed as ``Mapping`` rather than ``dict``: starlette's
    ``HTTPException.headers`` is declared as ``Mapping[str, str] | None`` and
    ``dict`` is invariant in its value type, so accepting only ``dict`` would
    reject the very argument this function exists to forward. The body is copied
    into a fresh dict below, so no mutation of the caller's mapping occurs.
    """
    request_id = getattr(request.state, REQUEST_ID_ATTR, None)
    body: dict[str, Any] = {
        "error": {
            "code": status_code,
            "message": detail,
            "request_id": request_id,
        }
    }
    if extra:
        body["error"].update(extra)

    response_headers: dict[str, str] = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content=body, headers=response_headers or None)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert HTTPException into the standard error envelope.

    The detail is passed through because it is authored by our own code (e.g.
    "You do not have permission to perform this action"), not derived from an
    internal error.

    ``exc.headers`` is forwarded. This is not cosmetic: RFC 6750 §3 requires a
    401 to carry ``WWW-Authenticate: Bearer``, and browsers, OAuth2 libraries and
    ``fastapi.testclient`` all rely on it to recognise an authentication failure.
    Rebuilding the response here without that header silently broke every 401 —
    the status code looked right while the contract was not.

    The parameter is typed ``Exception`` even though this handler is registered
    only for ``StarletteHTTPException``. Function parameters are contravariant,
    and starlette's ``add_exception_handler`` is typed to accept a callable
    taking ``Exception``; declaring the narrower type here makes mypy reject the
    registration. The ``isinstance`` guard keeps the narrowing real rather than
    asserted away with a cast — if starlette ever routes something else here, we
    produce a correct 500 instead of misreading unrelated attributes.
    """
    if not isinstance(exc, StarletteHTTPException):
        logger.exception(
            "http_exception_handler received %s",
            type(exc).__name__,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An internal server error occurred. Please quote the request id if you report this.",
        )
    return _error_response(request, exc.status_code, str(exc.detail), headers=exc.headers)


async def validation_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Convert Pydantic validation failures into the standard envelope.

    Field-level errors are surfaced — the client genuinely needs to know which
    field was rejected — but the raw exception object is not, since it can echo
    back submitted values including anything sensitive a caller put in a body.

    Typed ``Exception`` for the same contravariance reason as
    ``http_exception_handler`` above.
    """
    if not isinstance(exc, RequestValidationError):
        logger.exception(
            "validation_exception_handler received %s",
            type(exc).__name__,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An internal server error occurred. Please quote the request id if you report this.",
        )

    field_errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        # Drop the leading "body"/"query" marker; it is noise for the client.
        if location and location[0] in {"body", "query", "path", "header", "cookie"}:
            location = location[1:]
        field_errors.append(
            {
                "field": ".".join(location) or "<root>",
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
        )
    return _error_response(
        request,
        _UNPROCESSABLE_CONTENT,
        "Request validation failed",
        extra={"fields": field_errors},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: generic 500, no internals leaked.

    ``str(exc)`` is deliberately NOT included. Exception text routinely
    contains SQL fragments, file paths and connection strings — exactly what an
    attacker wants (OWASP A01/A05). The detail is already in the server log
    with the same request id, which is what support needs.
    """
    logger.exception(
        "Unhandled %s on %s %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
    )
    return _error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An internal server error occurred. Please quote the request id if you report this.",
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def register_middleware(app: FastAPI, settings: Settings | None = None) -> None:
    """Attach CORS, request-context middleware and the error handlers.

    Middleware registration order matters in Starlette: the **last** added is
    the outermost. We add CORS last so it wraps everything — including error
    responses, which otherwise reach the browser without CORS headers and
    surface as an opaque network error instead of a readable message.
    """
    cfg = settings or get_settings()
    app.state.settings = cfg

    app.add_middleware(RequestContextMiddleware)

    # Wildcard origins with credentials would let any site make authenticated
    # cross-origin calls. Starlette actually ignores allow_origins=["*"] when
    # credentials are on, but we refuse the combination outright so the mistake
    # cannot be made silently.
    allow_all_origins = "*" in cfg.cors_origin_list
    if allow_all_origins and cfg.is_production:
        msg = (
            "APP_CORS_ORIGINS must not contain '*' in production. "
            "List the exact frontend origins instead."
        )
        raise RuntimeError(msg)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all_origins else cfg.cors_origin_list,
        allow_credentials=not allow_all_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # Expose the request id so the frontend can show it in error dialogs.
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


def configure_logging(settings: Settings | None = None) -> None:
    """Set up structured logging with the request-id filter installed."""
    cfg = settings or get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(cfg.log_level.upper())

    # SQLAlchemy's echo would drown the app log; it has its own setting.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if cfg.db_echo_sql else logging.WARNING
    )


def get_request_id(request: Request) -> str | None:
    """Read the correlation id for the current request, if any.

    Used by services that write audit rows so the audit record can be joined
    back to the request log line.
    """
    return getattr(request.state, REQUEST_ID_ATTR, None)


def get_client_ip(request: Request) -> str | None:
    """Best-effort client IP, honouring a reverse proxy's X-Forwarded-For.

    Only the **first** forwarded address is used and the value is length-capped.
    X-Forwarded-For is client-controlled unless your proxy overwrites it — do
    not use this for security decisions, only for audit context. If you deploy
    behind a proxy you control, configure it to set the header authoritatively.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first and len(first) <= 45:
            return first
    client = request.client
    return client.host if client else None
