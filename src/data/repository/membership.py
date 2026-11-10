"""SQL for auth; callers own the transaction and audit commit boundary."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_policy(self) -> None:
        row = self.session.execute(
            select(AuthPolicyLock).where(AuthPolicyLock.id == 1).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise RuntimeError("Auth policy lock missing; apply Alembic migrations")

    def get_user(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def find_user(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email_normalized == email))

    def add_user(
        self,
        *,
        email_normalized: str,
        display_name: str,
        password_hash: str,
        role: str,
    ) -> User:
        user = User(
            email_normalized=email_normalized,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_session(self, sid: str) -> AuthSession | None:
        return self.session.get(AuthSession, sid)

    def find_refresh(self, digest: str) -> AuthSession | None:
        return self.session.scalar(
            select(AuthSession).where(AuthSession.current_refresh_digest == digest)
        )

    def find_used_refresh(self, digest: str) -> UsedRefreshToken | None:
        return self.session.get(UsedRefreshToken, digest)

    def add_session(
        self,
        *,
        id: str,  # noqa: A002 - persisted session identifier, mirrors the ORM field
        user_id: int,
        current_refresh_digest: str,
        expires_at: datetime,
    ) -> AuthSession:
        row = AuthSession(
            id=id,
            user_id=user_id,
            current_refresh_digest=current_refresh_digest,
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def remember_refresh(self, *, digest: str, session_id: str, expires_at: datetime) -> None:
        self.session.add(
            UsedRefreshToken(
                digest=digest,
                session_id=session_id,
                expires_at=expires_at,
            )
        )
        self.session.flush()

    def revoke_user_sessions(self, user_id: int, now: datetime) -> None:
        self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    def active_admin_count(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == "admin",
                    User.is_active.is_(True),
                )
            )
            or 0
        )

    def list_users(self, *, offset: int, limit: int) -> list[User]:
        return list(
            self.session.scalars(select(User).order_by(User.id).offset(offset).limit(limit))
        )

    def user_count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(User)) or 0)
