"""Authentication use cases. HTTP and SQL belong in the surrounding tiers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy.exc import IntegrityError

from src.common.audit import ACTION_USER_ROLE_CHANGED, record_audit
from src.common.config import Settings
from src.common.security import (
    InvalidTokenError,
    Role,
    TokenPayload,
    create_access_token,
    hash_password,
    verify_password,
)
from src.data.repository.membership import MembershipRepository
from src.data.schema.membership import AuthSession, User


class MembershipError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def utc(value: datetime) -> datetime:
    """MySQL DATETIME and SQLite return naive values; all persisted times are UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(refresh: str, settings: Settings) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), refresh.encode(), hashlib.sha256).hexdigest()


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email_normalized,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "version": user.version,
    }


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(24))


@dataclass
class LoginResult:
    data: dict[str, Any]
    refresh: str
    max_age: int


class MembershipService:
    def __init__(self, repository: MembershipRepository, settings: Settings) -> None:
        self.repo = repository
        self.settings = settings

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        role: Role = Role.CUSTOMER,
        actor: TokenPayload | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        hashed = hash_password(password)
        try:
            self.repo.lock_policy()
            if actor is not None:
                self._admin(actor)
            elif role != Role.CUSTOMER:
                raise MembershipError(403, "Permission denied")
            user = self.repo.add_user(
                email_normalized=email.strip().casefold(),
                display_name=display_name.strip(),
                password_hash=hashed,
                role=str(role),
            )
            if actor is not None:
                self._audit("user.created", user, actor, None, user_out(user), request_id)
            result = user_out(user)
            self.repo.session.commit()
            return result
        except IntegrityError as exc:
            self.repo.session.rollback()
            raise MembershipError(409, "Account already exists") from exc
        except Exception:
            self.repo.session.rollback()
            raise

    def login(self, email: str, password: str) -> LoginResult:
        # Hash verification happens before taking the global auth write lock.
        user = self.repo.find_user(email.strip().casefold())
        initial_hash = user.password_hash if user else _dummy_hash()
        valid = verify_password(password, initial_hash)
        self.repo.session.rollback()  # end the read snapshot before locking
        try:
            self.repo.lock_policy()
            user = self.repo.find_user(email.strip().casefold())
            if not valid or not user or not user.is_active or user.password_hash != initial_hash:
                raise MembershipError(401, "Invalid credentials")
            refresh = secrets.token_urlsafe(48)
            session = self.repo.add_session(
                id=secrets.token_urlsafe(24),
                user_id=user.id,
                current_refresh_digest=digest(refresh),
                expires_at=datetime.now(UTC)
                + timedelta(days=self.settings.refresh_token_expire_days),
            )
            result = self._result(user, session, refresh)
            self.repo.session.commit()
            return result
        except Exception:
            self.repo.session.rollback()
            raise

    def refresh(self, refresh: str) -> LoginResult:
        try:
            self.repo.lock_policy()
            session = self.repo.find_refresh(digest(refresh))
            now = datetime.now(UTC)
            if session is None:
                used = self.repo.find_used_refresh(digest(refresh))
                if used:
                    previous = self.repo.get_session(used.session_id)
                    if previous and previous.revoked_at is None:
                        previous.revoked_at = now
                        self.repo.session.commit()  # replay revocation must survive the 401
                raise MembershipError(401, "Invalid credentials")
            user = self.repo.get_user(session.user_id)
            if (
                session.revoked_at
                or utc(session.expires_at) <= now
                or not user
                or not user.is_active
            ):
                raise MembershipError(401, "Invalid credentials")
            self.repo.remember_refresh(
                digest=session.current_refresh_digest,
                session_id=session.id,
                expires_at=session.expires_at,
            )
            new_refresh = secrets.token_urlsafe(48)
            session.current_refresh_digest = digest(new_refresh)
            result = self._result(user, session, new_refresh)
            self.repo.session.commit()
            return result
        except Exception:
            self.repo.session.rollback()
            raise

    def logout(self, refresh: str | None) -> None:
        if not refresh:
            return
        try:
            self.repo.lock_policy()
            session = self.repo.find_refresh(digest(refresh))
            if session is None:
                used = self.repo.find_used_refresh(digest(refresh))
                session = self.repo.get_session(used.session_id) if used else None
            if session and session.revoked_at is None:
                session.revoked_at = datetime.now(UTC)
            self.repo.session.commit()
        except Exception:
            self.repo.session.rollback()
            raise

    def validate_identity(self, payload: TokenPayload) -> User:
        if not payload.sid or payload.auth_version is None:
            raise InvalidTokenError("Session is required")
        session = self.repo.get_session(payload.sid)
        user = self.repo.get_user(session.user_id) if session else None
        if (
            not session
            or session.revoked_at
            or utc(session.expires_at) <= datetime.now(UTC)
            or not user
            or not user.is_active
            or str(user.id) != payload.sub
            or user.role != payload.role
            or user.auth_version != payload.auth_version
        ):
            raise InvalidTokenError("Session is no longer valid")
        return user

    def change_user(
        self,
        user_id: int,
        *,
        actor: TokenPayload,
        version: int,
        role: Role | None = None,
        is_active: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            self.repo.lock_policy()
            self._admin(actor)
            user = self.repo.get_user(user_id)
            if user is None:
                raise MembershipError(404, "Account not found")
            if user.version != version:
                raise MembershipError(409, "Account changed; reload before retrying")
            before = {"role": user.role, "is_active": user.is_active}
            next_role = str(role) if role is not None else user.role
            next_active = is_active if is_active is not None else user.is_active
            if before == {"role": next_role, "is_active": next_active}:
                return user_out(user)
            if (
                user.role == Role.ADMIN
                and user.is_active
                and (next_role != Role.ADMIN or not next_active)
                and self.repo.active_admin_count() <= 1
            ):
                raise MembershipError(409, "At least one active administrator is required")
            user.role, user.is_active = next_role, next_active
            user.auth_version += 1
            self.repo.revoke_user_sessions(user.id, datetime.now(UTC))
            self._audit(
                ACTION_USER_ROLE_CHANGED if role is not None else "user.status_changed",
                user,
                actor,
                before,
                {"role": next_role, "is_active": next_active},
                request_id,
            )
            self.repo.session.flush()
            result = user_out(user)
            self.repo.session.commit()
            return result
        except Exception:
            self.repo.session.rollback()
            raise

    def bootstrap_admin(self, email: str, password: str, display_name: str) -> dict[str, Any]:
        hashed = hash_password(password)
        try:
            self.repo.lock_policy()
            if self.repo.user_count():
                raise MembershipError(409, "Bootstrap requires an empty user table")
            user = self.repo.add_user(
                email_normalized=email.strip().casefold(),
                password_hash=hashed,
                display_name=display_name,
                role=str(Role.ADMIN),
            )
            record_audit(
                self.repo.session,
                action="user.bootstrap",
                entity_type="User",
                entity_id=user.id,
                after={"role": str(Role.ADMIN)},
            )
            result = user_out(user)
            self.repo.session.commit()
            return result
        except Exception:
            self.repo.session.rollback()
            raise

    def _admin(self, actor: TokenPayload) -> None:
        user = self.validate_identity(actor)
        if user.role != Role.ADMIN:
            raise MembershipError(403, "Permission denied")

    def _result(self, user: User, session: AuthSession, refresh: str) -> LoginResult:
        token = create_access_token(
            user_id=user.id,
            role=user.role,
            settings=self.settings,
            extra_claims={"sid": session.id, "auth_version": user.auth_version},
        )
        return LoginResult(
            data={
                **token.model_dump(),
                "csrf_token": csrf_for(refresh, self.settings),
                "user": user_out(user),
            },
            refresh=refresh,
            max_age=max(0, int((utc(session.expires_at) - datetime.now(UTC)).total_seconds())),
        )

    def _audit(
        self,
        action: str,
        user: User,
        actor: TokenPayload,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        request_id: str | None,
    ) -> None:
        record_audit(
            self.repo.session,
            action=action,
            entity_type="User",
            entity_id=user.id,
            actor_id=actor.sub,
            actor_role=actor.role,
            before=before,
            after=after,
            request_id=request_id,
        )
