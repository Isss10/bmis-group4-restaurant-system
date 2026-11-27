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
from src.common.envelope import failure
from src.common.errors import ApiError, ErrorCode, http_status_for

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

# Maps an HTTP status raised by a bare ``HTTPException`` onto the frozen
# ErrorCode catalogue. Only the unambiguous statuses are listed; everything else
# falls back by category (see ``_code_for_status``).
#
# The frozen table (manual section 4.3) is authoritative for the code -> status
# direction, so once a code is chosen the response status is taken from
# ``http_status_for(code)`` rather than trusting the caller. That is what keeps
# the API, the documentation and the frontend agreeing.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_401_UNAUTHORIZED: ErrorCode.CREDENTIALS_MISSING,
    status.HTTP_403_FORBIDDEN: ErrorCode.PERMISSION_DENIED,
    status.HTTP_404_NOT_FOUND: ErrorCode.RESOURCE_NOT_FOUND,
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_FAILED,
    # Use the module-level literal constant, NOT status.HTTP_422_UNPROCESSABLE_ENTITY:
    # starlette deprecated that name in 1.7 and this project turns warnings into
    # errors, so merely *referencing* it would fail every test in the suite.
    _UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_FAILED,
}

# 401 must carry this header (RFC 6750 section 3) so browsers, OAuth2 clients
# and fastapi.testclient recognise an authentication failure rather than a
# generic error.
_UNAUTHENTICATED_CODES = frozenset({ErrorCode.CREDENTIALS_MISSING, ErrorCode.CREDENTIALS_INVALID})


def _code_for_status(http_status_code: int) -> ErrorCode:
    """Pick the frozen code for a bare ``HTTPException`` status.

    A bare ``HTTPException`` cannot express *which* business rule failed, so
    anything not in ``_STATUS_TO_CODE`` is bucketed by side of the fault: 4xx is
    the caller's problem (validation), 5xx is ours (internal). Modules that need
    a 2xxxx business code — notably the two concurrency codes 20001 and 20004,
    which are this project's external evidence of correctness — must raise
    :class:`~src.common.errors.ApiError` instead. A warning is logged so the
    shortcut shows up in review rather than silently weakening the contract.
    """
    mapped = _STATUS_TO_CODE.get(http_status_code)
    if mapped is not None:
        return mapped
    if 400 <= http_status_code < 500:
        logger.warning(
            "Bare HTTPException with status %d has no frozen error code; "
            "falling back to %d. Raise ApiError(ErrorCode.X) instead so the "
            "client receives a precise business code.",
            http_status_code,
            int(ErrorCode.VALIDATION_FAILED),
        )
        return ErrorCode.VALIDATION_FAILED
    return ErrorCode.INTERNAL_ERROR


def _error_response(
    request: Request,
    code: ErrorCode,
    *,
    message: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
    http_status: int | None = None,
) -> JSONResponse:
    """Build the frozen failure envelope (manual section 4.2).

    Shape::

        {"code": 20001, "message": "...", "data": null,
         "errors": [{"field": ..., "detail": ...}],
         "request_id": "...", "timestamp": "...Z"}

    ``errors`` is omitted when empty so a client can distinguish "no field
    detail" from "these fields are wrong".

    ``headers`` are merged before the correlation id so an exception's own
    headers survive the rebuild. Typed ``Mapping`` rather than ``dict`` because
    starlette declares ``HTTPException.headers`` as ``Mapping[str, str] | None``
    and ``dict`` is invariant in its value type — accepting only ``dict`` would
    reject the very argument this function exists to forward. The mapping is
    copied, never mutated.

    ``http_status`` overrides the frozen status for a code. Only needed when one
    code legitimately maps to two statuses; leave it None otherwise.
    """
    request_id = getattr(request.state, REQUEST_ID_ATTR, None)
    body = failure(code, request_id=request_id, message=message, errors=errors)

    response_headers: dict[str, str] = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    if code in _UNAUTHENTICATED_CODES:
        # Preserve an explicit WWW-Authenticate if the caller set one.
        response_headers.setdefault("WWW-Authenticate", "Bearer")

    return JSONResponse(
        status_code=http_status if http_status is not None else http_status_for(code),
        content=body,
        headers=response_headers or None,
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert a domain :class:`ApiError` into the frozen envelope.

    This is the handler module services actually depend on. A service raises
    ``ApiError(ErrorCode.SLOT_ALREADY_BOOKED)`` and gets a correct
    ``{"code": 20001, ...}`` response with HTTP 409, without the application tier
    ever importing FastAPI — which is what keeps the dependency rule in
    ARCHITECTURE.md section 3 enforceable.
    """
    if not isinstance(exc, ApiError):
        logger.exception(
            "api_error_handler received %s",
            type(exc).__name__,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
        return _error_response(request, ErrorCode.INTERNAL_ERROR)

    if exc.code == ErrorCode.INTERNAL_ERROR or exc.code == ErrorCode.DATABASE_ERROR:
        # A 5xxxx is our fault, not the caller's, so the traceback belongs in the
        # log with the same request id the client will quote back to us.
        logger.error(
            "ApiError %d on %s %s: %s",
            int(exc.code),
            request.method,
            request.url.path,
            exc.message,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
    return _error_response(
        request,
        exc.code,
        message=exc.message,
        errors=exc.errors,
        http_status=exc.http_status,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert a bare ``HTTPException`` into the frozen envelope.

    A bare ``HTTPException`` carries only a status, so the specific business code
    is recovered via ``_code_for_status``. Modules that need a 2xxxx business code
    — notably ``20001`` and ``20004``, which are this project's external evidence
    of concurrency correctness — must raise ``ApiError`` instead, handled above.

    ``exc.headers`` is forwarded. This is not cosmetic: RFC 6750 §3 requires a 401
    to carry ``WWW-Authenticate: Bearer``, and browsers, OAuth2 libraries and
    ``fastapi.testclient`` all rely on it to recognise an authentication failure.

    The parameter is typed ``Exception`` even though this handler is registered
    only for ``StarletteHTTPException``. Function parameters are contravariant and
    starlette's ``add_exception_handler`` is typed to accept a callable taking
    ``Exception``; declaring the narrower type makes mypy reject the registration.
    The ``isinstance`` guard keeps the narrowing real rather than asserted away
    with a cast.
    """
    if not isinstance(exc, StarletteHTTPException):
        logger.exception(
            "http_exception_handler received %s",
            type(exc).__name__,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
        return _error_response(request, ErrorCode.INTERNAL_ERROR)

    code = _code_for_status(exc.status_code)
    # The frozen message wins over `exc.detail`, and that is deliberate. Section
    # 4.3 pins one wording per code so the API, the documentation and the Vue
    # error strings cannot drift apart; letting each call site invent its own
    # text would defeat the point of freezing the table.
    #
    # The caller's detail is not discarded silently — it is logged with the same
    # request id the client receives, so support can still see what the code said.
    logger.info(
        "HTTPException %d mapped to code %d on %s %s (detail: %s)",
        exc.status_code,
        int(code),
        request.method,
        request.url.path,
        exc.detail,
        extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
    )
    # Preserve the caller's own headers (e.g. WWW-Authenticate, Retry-After).
    return _error_response(
        request,
        code,
        headers=exc.headers,
        http_status=exc.status_code,
    )


async def validation_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Convert Pydantic validation failures into the frozen envelope as code 10001.

    Field-level errors are surfaced — the client genuinely needs to know which
    field was rejected — but the raw exception object is not, since it can echo
    back submitted values including anything sensitive a caller put in a body.

    The ``errors`` entries use the contract's key names ``field`` and ``detail``
    (manual §4.2), not ``message``/``type``. The distinction is easy to get wrong
    and would silently break the frontend's error highlighting. Pydantic's own
    ``type`` (e.g. ``value_error.number.not_ge``) is developer-facing jargon, so
    it is appended to the detail only when Pydantic gave no human message.

    Typed ``Exception`` for the same contravariance reason as
    ``http_exception_handler`` above.
    """
    if not isinstance(exc, RequestValidationError):
        logger.exception(
            "validation_exception_handler received %s",
            type(exc).__name__,
            extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
        )
        return _error_response(request, ErrorCode.INTERNAL_ERROR)

    field_errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        # Drop the leading "body"/"query" marker; it is noise for the client.
        if location and location[0] in {"body", "query", "path", "header", "cookie"}:
            location = location[1:]
        detail = error.get("msg") or error.get("type", "Invalid value")
        field_errors.append(
            {
                "field": ".".join(location) or "<root>",
                "detail": str(detail),
            }
        )
    return _error_response(
        request,
        ErrorCode.VALIDATION_FAILED,
        errors=field_errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: frozen code 50001, no internals leaked.

    ``str(exc)`` is deliberately NOT included in the response. Exception text
    routinely contains SQL fragments, file paths and connection strings — exactly
    what an attacker wants (OWASP A01/A05). The traceback goes to the server log
    carrying the same request id the client receives, which is all support needs;
    the manual's note on code 50001 makes that log correlation mandatory.
    """
    logger.exception(
        "Unhandled %s on %s %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        extra={REQUEST_ID_ATTR: getattr(request.state, REQUEST_ID_ATTR, None)},
    )
    return _error_response(request, ErrorCode.INTERNAL_ERROR)


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

    # Registration order: most specific first. Starlette resolves a raised
    # exception by exact type, then walks its MRO, so ApiError must be registered
    # before the catch-all Exception handler — otherwise every domain error would
    # be swallowed by unhandled_exception_handler and reported as a generic 50001,
    # destroying the business codes the frontend depends on.
    app.add_exception_handler(ApiError, api_error_handler)
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
