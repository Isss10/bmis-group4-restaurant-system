"""Unit tests for src.common.audit — redaction, diffing and safe serialisation.

`record_audit` is exercised against an in-memory SQLite database so these tests
need no MySQL and run in CI on every pull request. SQLite is sufficient here
because we are testing the audit module's own logic (redaction, atomicity of the
add-to-session), not MySQL-specific behaviour.

The redaction tests matter most: Objective (f) requires audit logs, and an audit
table that stores passwords or tokens would itself be a security incident
(OWASP A09).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.common.audit import (
    ACTION_POINTS_ADJUSTED,
    ACTION_RESERVATION_STATUS_CHANGED,
    AuditLog,
    diff_dicts,
    record_audit,
    serialise_for_audit,
)


@pytest.fixture
def memory_session() -> Generator[Session, None, None]:
    """A SQLite in-memory session with the audit table created."""
    engine = create_engine("sqlite:///:memory:")
    # Only create the audit table: the full schema uses MySQL-specific types
    # that SQLite does not understand, and these tests do not need it.
    AuditLog.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Redaction — the security-critical behaviour
# ---------------------------------------------------------------------------


class TestRedaction:
    @pytest.mark.parametrize(
        "sensitive_key",
        [
            "password",
            "user_password",
            "PASSWORD",
            "Password",
            "passwd",
            "pwd",
            "secret",
            "jwt_secret",
            "token",
            "access_token",
            "refresh_token",
            "authorization",
            "credential",
            "credentials",
            "private_key",
            "api_key",
            "apikey",
            "cvv",
            "card_number",
            "session_id",
            "cookie",
        ],
    )
    def test_credential_keys_are_replaced_in_details(
        self, memory_session: Session, sensitive_key: str
    ) -> None:
        """No credential-like key survives into the stored row."""
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            details={sensitive_key: "hunter2"},
        )
        assert entry.details[sensitive_key] == "[REDACTED]"
        assert "hunter2" not in str(entry.details)

    def test_redaction_applies_to_before_and_after_snapshots(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="7",
            before={"password_hash": "abc123", "status": "pending"},
            after={"password_hash": "abc123", "status": "confirmed"},
        )
        assert entry.before["password_hash"] == "[REDACTED]"
        assert entry.after["password_hash"] == "[REDACTED]"
        # Non-sensitive fields are preserved — redaction must not destroy the record.
        assert entry.before["status"] == "pending"
        assert entry.after["status"] == "confirmed"

    def test_nested_credentials_are_redacted(self, memory_session: Session) -> None:
        """Redaction must recurse; a nested token is just as dangerous."""
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            details={
                "request": {"headers": {"authorization": "Bearer secret-jwt-value"}},
                "accounts": [{"api_key": "key-value"}],
                "safe": "keep me",
            },
        )
        assert entry.details["request"]["headers"]["authorization"] == "[REDACTED]"
        assert entry.details["accounts"][0]["api_key"] == "[REDACTED]"
        assert entry.details["safe"] == "keep me"

    def test_secret_value_nowhere_in_the_persisted_row(self, memory_session: Session) -> None:
        """End-to-end check: the stored row contains no trace of the secret."""
        secret_value = "s3cr3t-that-must-not-be-persisted"
        record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            before={"password": secret_value},
            after={"password": secret_value},
            details={"token": secret_value},
            message="adjusted points",
        )
        memory_session.commit()
        stored = memory_session.execute(select(AuditLog)).scalar_one()
        serialised = f"{stored.before}{stored.after}{stored.details}{stored.message}"
        assert secret_value not in serialised

    def test_non_sensitive_keys_are_untouched(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="7",
            details={"reason": "customer called", "table": 12, "guests": 4},
        )
        assert entry.details == {"reason": "customer called", "table": 12, "guests": 4}

    def test_redaction_does_not_mutate_the_caller_dict(self, memory_session: Session) -> None:
        """The caller's dict is still in use by the live request.

        Mutating it would silently blank fields the request handler still needs.
        """
        original = {"password": "keep-intact", "status": "confirmed"}
        record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="7",
            details=original,
        )
        assert original == {"password": "keep-intact", "status": "confirmed"}


# ---------------------------------------------------------------------------
# Field storage
# ---------------------------------------------------------------------------


class TestRecordAudit:
    def test_row_is_added_to_the_session(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
        )
        assert entry in memory_session.new or entry.id is not None

    def test_row_is_not_committed_by_default(self, memory_session: Session) -> None:
        """Atomicity: the audit row must commit or roll back with its business change.

        An audit trail describing a change that never happened is worse than none.
        """
        record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
        )
        memory_session.rollback()
        assert memory_session.execute(select(AuditLog)).scalar_one_or_none() is None

    def test_rollback_discards_the_audit_row(self, memory_session: Session) -> None:
        record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="7",
        )
        memory_session.commit()
        assert memory_session.execute(select(AuditLog)).one() is not None

        record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="8",
        )
        memory_session.rollback()
        rows = memory_session.execute(select(AuditLog)).scalars().all()
        assert len(rows) == 1
        assert rows[0].entity_id == "7"

    def test_numeric_ids_are_stringified(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id=42,
            actor_id=7,
            actor_role="manager",
        )
        assert entry.entity_id == "42"
        assert entry.actor_id == "7"

    def test_none_entity_id_is_allowed(self, memory_session: Session) -> None:
        """System-level actions (a failed login) have no single affected row."""
        entry = record_audit(
            memory_session,
            action="auth.login_failure",
            entity_type="User",
            entity_id=None,
        )
        assert entry.entity_id is None

    def test_occurred_at_is_utc_and_recent(self, memory_session: Session) -> None:
        before = datetime.now(UTC)
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
        )
        after = datetime.now(UTC)
        stored = entry.occurred_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert before <= stored <= after

    def test_long_user_agent_is_truncated(self, memory_session: Session) -> None:
        """The column is VARCHAR(512); an over-long header must not blow up the insert."""
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            user_agent="M" * 2000,
        )
        assert len(entry.user_agent) == 512

    def test_request_metadata_is_stored(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            actor_id="7",
            actor_role="manager",
            ip_address="203.0.113.9",
            request_id="abc123def456abc123def456abc123de",
            message="Manual points adjustment",
        )
        assert entry.actor_role == "manager"
        assert entry.ip_address == "203.0.113.9"
        assert entry.request_id == "abc123def456abc123def456abc123de"
        assert entry.message == "Manual points adjustment"

    def test_flush_false_leaves_the_row_pending(self, memory_session: Session) -> None:
        entry = record_audit(
            memory_session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="User",
            entity_id="1",
            flush=False,
        )
        # Not flushed, so no primary key has been assigned yet.
        assert entry.id is None
        memory_session.flush()
        assert entry.id is not None

    def test_multiple_rows_accumulate_in_one_transaction(self, memory_session: Session) -> None:
        """A staff action touching several entities writes several rows."""
        for index in range(5):
            record_audit(
                memory_session,
                action=ACTION_POINTS_ADJUSTED,
                entity_type="User",
                entity_id=index,
            )
        memory_session.commit()
        assert len(memory_session.execute(select(AuditLog)).scalars().all()) == 5


# ---------------------------------------------------------------------------
# diff_dicts
# ---------------------------------------------------------------------------


class TestDiffDicts:
    def test_only_changed_fields_are_returned(self) -> None:
        before, after = diff_dicts(
            {"status": "pending", "guests": 4, "table": 12},
            {"status": "confirmed", "guests": 4, "table": 12},
        )
        assert before == {"status": "pending"}
        assert after == {"status": "confirmed"}

    def test_identical_dicts_produce_empty_diff(self) -> None:
        before, after = diff_dicts({"status": "pending"}, {"status": "pending"})
        assert before == {}
        assert after == {}

    def test_added_and_removed_keys_appear(self) -> None:
        before, after = diff_dicts({"a": 1}, {"b": 2})
        assert before == {"a": 1, "b": None}
        assert after == {"a": None, "b": 2}

    def test_fields_argument_restricts_comparison(self) -> None:
        """Ignore noisy fields like updated_at that change on every write."""
        before, after = diff_dicts(
            {"status": "pending", "updated_at": "2026-01-01", "note": "x"},
            {"status": "confirmed", "updated_at": "2026-01-02", "note": "y"},
            fields=["status"],
        )
        assert before == {"status": "pending"}
        assert after == {"status": "confirmed"}

    def test_result_is_deterministically_ordered(self) -> None:
        """Sorted keys make diffs readable and comparisons stable."""
        before, _ = diff_dicts({"z": 1, "a": 2}, {"z": 9, "a": 8})
        assert list(before) == ["a", "z"]

    def test_diff_feeds_straight_into_record_audit(self, memory_session: Session) -> None:
        """The two helpers are designed to be used together."""
        changed_before, changed_after = diff_dicts(
            {"status": "pending", "guests": 4},
            {"status": "confirmed", "guests": 4},
        )
        entry = record_audit(
            memory_session,
            action=ACTION_RESERVATION_STATUS_CHANGED,
            entity_type="Reservation",
            entity_id="7",
            before=changed_before,
            after=changed_after,
        )
        assert entry.before == {"status": "pending"}
        assert entry.after == {"status": "confirmed"}


# ---------------------------------------------------------------------------
# serialise_for_audit
# ---------------------------------------------------------------------------


class TestSerialiseForAudit:
    @pytest.mark.parametrize("value", [None, "text", 42, 3.14, True, False])
    def test_scalars_pass_through_unchanged(self, value: Any) -> None:
        assert serialise_for_audit(value) == value

    def test_datetime_becomes_iso_8601(self) -> None:
        moment = datetime(2026, 10, 10, 12, 30, tzinfo=UTC)
        assert serialise_for_audit(moment) == "2026-10-10T12:30:00+00:00"

    def test_decimal_becomes_its_repr(self) -> None:
        """Decimal is not JSON-native; degrading to repr keeps the audit write alive."""
        result = serialise_for_audit(Decimal("19.99"))
        assert "19.99" in str(result)

    def test_nested_structures_are_converted(self) -> None:
        result = serialise_for_audit(
            {"when": datetime(2026, 1, 1, tzinfo=UTC), "items": [1, "two"]}
        )
        assert result["when"] == "2026-01-01T00:00:00+00:00"
        assert result["items"] == [1, "two"]

    def test_sets_become_lists(self) -> None:
        assert sorted(serialise_for_audit({3, 1, 2})) == [1, 2, 3]

    def test_unserialisable_object_degrades_to_truncated_repr(self) -> None:
        class Opaque:
            pass

        result = serialise_for_audit(Opaque())
        assert isinstance(result, str)
        assert "Opaque" in result

    def test_very_large_repr_is_truncated(self) -> None:
        """A giant object must not bloat the audit table."""

        class Huge:
            def __repr__(self) -> str:
                return "x" * 5000

        assert len(serialise_for_audit(Huge())) == 500

    def test_never_raises_on_unexpected_input(self) -> None:
        """Raising here would abort the business transaction being audited."""
        for value in [object(), lambda: None, {1, 2}, (datetime.now(UTC),)]:
            serialise_for_audit(value)  # must not raise
