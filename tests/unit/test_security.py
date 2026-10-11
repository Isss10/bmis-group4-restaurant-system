"""Unit tests for src.common.security — password hashing, JWT and RBAC.

These are the tests that protect the highest-risk item in the OWASP Top 10 for
this project (A01 Broken Access Control): a waiter must never reach manager
data, and a customer must never reach the back office at all.
"""

from __future__ import annotations

import time

import jwt
import pytest

from src.common.config import get_settings
from src.common.security import (
    ANALYTICS_VIEWERS,
    REVIEW_MODERATORS,
    InvalidTokenError,
    Role,
    TokenPayload,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class TestRole:
    def test_all_four_roles_from_proposal_exist(self) -> None:
        """Objective (c) names exactly these four roles."""
        assert {role.value for role in Role} == {"customer", "waiter", "manager", "admin"}

    def test_role_serialises_to_plain_string(self) -> None:
        """StrEnum means the JWT claim and DB column hold a bare lowercase string."""
        assert str(Role.MANAGER) == "manager"
        assert Role.CUSTOMER == "customer"

    def test_customer_is_not_staff(self) -> None:
        assert Role.CUSTOMER.is_staff is False

    @pytest.mark.parametrize("role", [Role.WAITER, Role.MANAGER, Role.ADMIN])
    def test_back_office_roles_are_staff(self, role: Role) -> None:
        assert role.is_staff is True

    def test_customer_excluded_from_moderators_and_analytics(self) -> None:
        """A customer must not appear in any privileged role set."""
        assert Role.CUSTOMER not in REVIEW_MODERATORS
        assert Role.CUSTOMER not in ANALYTICS_VIEWERS
        assert Role.WAITER not in ANALYTICS_VIEWERS


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext(self) -> None:
        hashed = hash_password("Sup3r-Secret!")
        assert hashed != "Sup3r-Secret!"
        assert "Sup3r-Secret!" not in hashed

    def test_hash_uses_bcrypt(self) -> None:
        assert hash_password("anything").startswith("$2")

    def test_same_password_produces_different_hashes(self) -> None:
        """Salting must make two identical passwords hash differently.

        If this ever fails, the hash is unsalted and a rainbow table works.
        """
        assert hash_password("same-password") != hash_password("same-password")

    def test_verify_accepts_the_correct_password(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True

    def test_verify_rejects_a_wrong_password(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("wrong horse battery staple", hashed) is False

    def test_verify_rejects_empty_password(self) -> None:
        hashed = hash_password("not-empty")
        assert verify_password("", hashed) is False

    def test_verify_survives_a_corrupt_hash(self) -> None:
        """A malformed stored hash must return False, not raise.

        Otherwise one corrupt row becomes a 500 that leaks internals.
        """
        assert verify_password("anything", "not-a-valid-hash") is False
        assert verify_password("anything", "") is False

    def test_hash_rejects_empty_password(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            hash_password("")

    def test_hash_rejects_password_beyond_bcrypt_limit(self) -> None:
        """bcrypt silently truncates past 72 bytes; we refuse instead.

        A 200-character password would be accepted, but only its first 72 bytes
        would actually be checked — a real weakening of the credential.
        """
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password("x" * 73)

    def test_hash_accepts_exactly_72_bytes(self) -> None:
        password = "x" * 72
        assert verify_password(password, hash_password(password)) is True

    def test_multibyte_characters_count_as_bytes(self) -> None:
        """The limit is on UTF-8 bytes, not characters.

        25 CJK characters are 75 bytes in UTF-8, so this must be rejected even
        though it is well under 72 *characters*.
        """
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password("密" * 25)

    def test_unicode_password_roundtrips(self) -> None:
        password = "正确的马电池钉书钉🔒"
        assert verify_password(password, hash_password(password)) is True

    def test_fresh_hash_does_not_need_rehash(self) -> None:
        assert password_needs_rehash(hash_password("password")) is False

    def test_garbage_hash_is_reported_as_needing_rehash(self) -> None:
        assert password_needs_rehash("garbage") is True


# ---------------------------------------------------------------------------
# JWT issuing
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    def test_token_is_a_non_empty_string(self) -> None:
        assert create_access_token(user_id=7, role=Role.CUSTOMER).access_token

    def test_token_pair_metadata(self) -> None:
        pair = create_access_token(user_id=7, role=Role.CUSTOMER)
        assert pair.token_type == "bearer"
        settings = get_settings()
        assert pair.expires_in == settings.access_token_expire_minutes * 60

    def test_int_user_id_is_stringified_in_the_sub_claim(self) -> None:
        pair = create_access_token(user_id=42, role=Role.WAITER)
        decoded = decode_access_token(pair.access_token)
        assert decoded.sub == "42"

    def test_claims_contain_role_and_timestamps(self) -> None:
        pair = create_access_token(user_id="u1", role=Role.MANAGER)
        payload = decode_access_token(pair.access_token)
        assert payload.role is Role.MANAGER
        assert payload.iat <= int(time.time())
        assert payload.exp > payload.iat

    def test_each_token_has_a_unique_jti(self) -> None:
        """jti must be unique so a leaked token can be revoked by id."""

        def issue() -> TokenPayload:
            return decode_access_token(
                create_access_token(user_id=1, role=Role.CUSTOMER).access_token
            )

        assert issue().jti != issue().jti

    def test_extra_claims_are_included(self) -> None:
        pair = create_access_token(
            user_id=1,
            role=Role.CUSTOMER,
            extra_claims={"tier": "gold"},
        )
        raw = jwt.decode(
            pair.access_token,
            get_settings().jwt_secret_key,
            algorithms=[get_settings().jwt_algorithm],
        )
        assert raw["tier"] == "gold"

    @pytest.mark.parametrize("reserved", ["sub", "role", "exp", "iat", "jti"])
    def test_extra_claims_cannot_override_reserved_claims(self, reserved: str) -> None:
        """A caller must not be able to escalate their own role via extra_claims."""
        with pytest.raises(ValueError, match="reserved claims"):
            create_access_token(
                user_id=1,
                role=Role.CUSTOMER,
                extra_claims={reserved: "attacker-controlled"},
            )

    def test_refuses_to_sign_without_a_secret(self) -> None:
        """An empty secret would let anyone forge a valid token."""
        blank = get_settings().model_copy(update={"jwt_secret_key": ""})
        with pytest.raises(RuntimeError, match="APP_JWT_SECRET_KEY"):
            create_access_token(user_id=1, role=Role.CUSTOMER, settings=blank)


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


class TestDecodeAccessToken:
    def test_rejects_a_forged_signature(self) -> None:
        pair = create_access_token(user_id=1, role=Role.CUSTOMER)
        # The attacker's secret must be *wrong*, not merely *short*. PyJWT warns
        # (InsecureKeyLengthWarning) below 32 bytes for HS256, and this project
        # runs pytest with `filterwarnings = ["error"]`, so a short literal here
        # would fail the test for the wrong reason and hide what it asserts.
        # 44 chars keeps the intent: a plausible-length but incorrect key.
        attacker_secret = "attacker-guessed-secret-value-that-is-long-enough"
        assert len(attacker_secret) >= 32
        forged = jwt.encode(
            {"sub": "1", "role": "admin", "iat": int(time.time()), "exp": int(time.time()) + 60},
            attacker_secret,
            algorithm="HS256",
        )
        assert forged != pair.access_token
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged)

    def test_rejects_an_expired_token(self) -> None:
        """A token whose exp has passed must not verify.

        Built by hand with the real secret so the signature is valid — the only
        reason it can fail is expiry, which is what we are asserting.
        """
        settings = get_settings()
        expired = jwt.encode(
            {
                "sub": "1",
                "role": "customer",
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 3600,
                "jti": "test",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(expired)

    def test_rejects_a_token_missing_required_claims(self) -> None:
        settings = get_settings()
        incomplete = jwt.encode(
            {"sub": "1", "exp": int(time.time()) + 60},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(incomplete)

    def test_rejects_a_token_with_an_unknown_role(self) -> None:
        """A well-signed token carrying a bogus role must not become a user.

        This is what stops someone minting a token with role "superadmin" and
        passing Pydantic validation into a privilege they were never granted.
        """
        settings = get_settings()
        bad_role = jwt.encode(
            {
                "sub": "1",
                "role": "superadmin",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
                "jti": "x",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError, match="malformed"):
            decode_access_token(bad_role)

    def test_rejects_garbage_input(self) -> None:
        with pytest.raises(InvalidTokenError):
            decode_access_token("this.is.not-a-token")

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(InvalidTokenError):
            decode_access_token("")

    def test_error_message_does_not_leak_the_reason(self) -> None:
        """Client-facing text must not distinguish expired from forged.

        Telling an attacker "signature invalid" versus "token expired" is useful
        reconnaissance. Internally we chain the real cause; externally we do not.
        """
        with pytest.raises(InvalidTokenError) as excinfo:
            decode_access_token("garbage")
        assert "expired" not in str(excinfo.value).lower()
        assert "signature" not in str(excinfo.value).lower()

    def test_rejects_the_none_algorithm(self) -> None:
        """The classic JWT `alg: none` bypass must not verify."""
        unsecured = jwt.encode(
            {"sub": "1", "role": "admin", "iat": int(time.time()), "exp": int(time.time()) + 60},
            key="",
            algorithm="none",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(unsecured)

    def test_token_payload_is_a_pydantic_model(self) -> None:
        pair = create_access_token(user_id=1, role=Role.ADMIN)
        payload: TokenPayload = decode_access_token(pair.access_token)
        assert isinstance(payload, TokenPayload)


# ---------------------------------------------------------------------------
# Guard builders
# ---------------------------------------------------------------------------


class TestRequireRoles:
    def test_rejects_an_empty_role_list(self) -> None:
        """require_roles() with no roles would permit nobody — a silent bug.

        This is a synchronous call: the validation happens while building the
        guard, before any coroutine is returned.
        """
        from src.common.security import require_roles

        with pytest.raises(ValueError, match="at least one role"):
            require_roles()

    def test_guards_return_callable_dependencies(self) -> None:
        from src.common.security import (
            require_analytics_viewer,
            require_review_moderator,
            require_roles,
            require_staff,
        )

        assert callable(require_roles(Role.ADMIN))
        assert callable(require_staff())
        assert callable(require_review_moderator())
        assert callable(require_analytics_viewer())
