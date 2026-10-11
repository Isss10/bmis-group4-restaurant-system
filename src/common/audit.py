"""Audit logging for back-office changes.

Objective (f) requires "audit logs for back-office changes". This module
provides both:

* :class:`AuditLog` — the database table (the durable, queryable record), and
* :func:`record_audit` — the helper every service calls after a mutation.

Why a database table and not just log lines
-------------------------------------------
Log files rotate and are lost; an auditor or a manager asking "who changed
this reservation's status last Tuesday?" needs a queryable record that survives
restarts. We still emit a structured log line too, so operations can tail it
live.

What gets recorded
------------------
Every state-changing action performed by staff (waiter / manager / admin) —
reservation status changes, order handling, review moderation, points
adjustments, coupon issuance, schema-affecting admin actions. Read-only
operations are not audited; that would bury the signal in noise.

OWASP relevance
---------------
A09:2021 Security Logging and Alerting Failures. Note what we deliberately do
**not** store: plaintext passwords, full JWTs, payment data, or any
free-text field that might contain personal data. `details` is JSON supplied by
the caller and must be reviewed against that rule — see `_redact`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.common.config import get_settings
from src.data.database import Base

logger = logging.getLogger("audit")

# Keys whose values are never safe to persist, whatever the caller passes.
# Matching is case-insensitive on substring, so "user_password" is caught too.
_REDACT_KEY_FRAGMENTS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "authorization",
        "credential",
        "private_key",
        "api_key",
        "apikey",
        "cvv",
        "card_number",
        "session_id",
        "cookie",
    }
)

_REDACTED = "[REDACTED]"


# Canonical action names.
#
# These are module-level string constants rather than a Python enum because the
# values are written straight into a VARCHAR column and read back by raw SQL
# queries and the manager dashboard; a plain string round-trips with no
# conversion layer. Keeping them in one place still gives the vocabulary a
# single source of truth and makes typos an AttributeError instead of a silent
# "unknown action" row. Add new actions here.
ACTION_RESERVATION_CREATED = "reservation.created"
ACTION_RESERVATION_STATUS_CHANGED = "reservation.status_changed"
ACTION_RESERVATION_CANCELLED = "reservation.cancelled"
ACTION_RESERVATION_NO_SHOW = "reservation.no_show"
ACTION_SEAT_HOLD_EXPIRED = "seat_hold.expired"
ACTION_ORDER_CREATED = "order.created"
ACTION_ORDER_STATUS_CHANGED = "order.status_changed"
ACTION_REVIEW_SUBMITTED = "review.submitted"
ACTION_REVIEW_MODERATED = "review.moderated"
ACTION_REVIEW_REMOVED = "review.removed"
ACTION_POINTS_ADJUSTED = "points.adjusted"
ACTION_COUPON_ISSUED = "coupon.issued"
ACTION_COUPON_REDEEMED = "coupon.redeemed"
ACTION_USER_ROLE_CHANGED = "user.role_changed"
ACTION_LOGIN_SUCCESS = "auth.login_success"
ACTION_LOGIN_FAILURE = "auth.login_failure"


def _redact(value: Any) -> Any:
    """Recursively strip credential-like keys from a JSON-serialisable value.

    Returns a copy — never mutate the caller's dict, since it is usually still
    in use by the request being audited.
    """
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(fragment in key_lower for fragment in _REDACT_KEY_FRAGMENTS):
                cleaned[str(key)] = _REDACTED
            else:
                cleaned[str(key)] = _redact(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class AuditLog(Base):
    """One row per audited back-office action."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(UTC),
        comment="UTC timestamp of the action, set by the application",
    )

    actor_id: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="User id from the JWT sub claim; NULL for anonymous/system actions",
    )

    actor_role: Mapped[str] = mapped_column(
        String(32),
        nullable=True,
        comment="Role at the time of the action, so history survives role changes",
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Controlled vocabulary, e.g. reservation.status_changed",
    )

    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Type of the affected object, e.g. Reservation",
    )

    entity_id: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Identifier of the affected object",
    )

    before: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Redacted snapshot of the changed fields before the action",
    )

    after: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Redacted snapshot of the changed fields after the action",
    )

    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Additional redacted context, e.g. the reason given for a change",
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="Client IP. 45 chars covers IPv6 in IPv4-mapped form.",
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Truncated User-Agent header",
    )

    request_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Correlates all audit rows produced by one HTTP request",
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable summary for the manager UI",
    )

    __table_args__ = (
        # The manager dashboard queries "who touched what, when" — this covers
        # both the actor-centric and the entity-centric access patterns.
        Index("ix_audit_actor_time", "actor_id", "occurred_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_action_time", "action", "occurred_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog {self.action} {self.entity_type}#{self.entity_id} "
            f"by {self.actor_id} at {self.occurred_at}>"
        )


def record_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_id: str | int | None = None,
    actor_role: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    message: str | None = None,
    flush: bool = True,
) -> AuditLog:
    """Append an audit record inside the caller's transaction.

    The row is added to `session` but **not committed** — it commits or rolls
    back together with the business change it describes. That atomicity is the
    point: an audit trail that records a change which never happened is worse
    than no trail, and a change with no trail is exactly what we are preventing.

    Pass ``flush=True`` (default) to make the row visible to later queries in
    the same transaction and to surface constraint violations immediately.

    Args:
        session: the active session, typically from ``Depends(get_db)``.
        action: one of the ``ACTION_*`` constants above.
        entity_type: affected model name, e.g. ``"Reservation"``.
        entity_id: affected row id, stringified for uniform storage.
        actor_id: authenticated user id, or None for system jobs.
        actor_role: role at action time.
        before/after: field snapshots; credential-like keys are stripped.
        details: extra context; also stripped.
        ip_address/user_agent/request_id: request metadata for correlation.
        message: human-readable summary.
        flush: whether to flush immediately.

    Returns:
        The created :class:`AuditLog` instance.
    """
    settings = get_settings()
    entry = AuditLog(
        occurred_at=datetime.now(UTC),
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_role=str(actor_role) if actor_role else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_redact(before) if before is not None else None,
        after=_redact(after) if after is not None else None,
        details=_redact(details) if details is not None else None,
        ip_address=ip_address,
        user_agent=(user_agent[:512] if user_agent else None),
        request_id=request_id,
        message=message,
    )
    session.add(entry)

    # Mirror to the application log so the trail is tail-able in real time.
    # Controlled by a setting so a noisy test run can silence it.
    if settings.audit_log_enabled:
        logger.info(
            "audit",
            extra={
                "audit_action": action,
                "audit_entity": f"{entity_type}#{entry.entity_id}",
                "audit_actor": entry.actor_id,
                "audit_role": entry.actor_role,
            },
        )

    if flush:
        session.flush()
    return entry


def diff_dicts(
    before: dict[str, Any],
    after: dict[str, Any],
    fields: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return only the fields that actually changed, as (before, after) pairs.

    Storing full row snapshots for every action bloats the table fast. Callers
    pass the complete dicts and get back the minimal change set, which is what
    an auditor actually wants to read.

    Args:
        before: field values prior to the change.
        after: field values following the change.
        fields: restrict the comparison to these keys; defaults to the union.

    Returns:
        A tuple of two dicts containing only changed keys.
    """
    keys = fields if fields is not None else sorted(set(before) | set(after))
    changed_before: dict[str, Any] = {}
    changed_after: dict[str, Any] = {}
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changed_before[key] = old
            changed_after[key] = new
    return changed_before, changed_after


def serialise_for_audit(value: Any) -> Any:
    """Convert a value to something JSON-serialisable, safely.

    SQLAlchemy model instances, datetimes and Decimals all turn up in snapshots.
    Rather than raising on an unexpected type (which would abort the audited
    business transaction — unacceptable), unknown objects degrade to their repr.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): serialise_for_audit(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialise_for_audit(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)[:500]
