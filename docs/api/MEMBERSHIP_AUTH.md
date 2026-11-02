# Membership authentication API — Member10 / T4

Implementation target: 12 November 2026 (Member10's requested early delivery).
The proposal's full T4 deadline remains 23 November; Member4 owns loyalty rules.
Generated request/response schemas: [openapi.json](openapi.json).

## Contract and compatibility

This implementation extends **current main**, not the unmerged contract-alignment branch.
Successful responses are the DTO itself. Errors retain
`{"error":{"code":<HTTP status>,"message":<text>,"request_id":<id>}}`.
No five-digit codes or response envelope are silently introduced. Keep the existing
`GET /api/v1/auth/me` response fields: user_id, role, token_id, expires_at.
Its token now must identify a live database session; old hand-minted tokens without
`sid` and `auth_version` are rejected. Clients obtain tokens from the login endpoint.
API/schema/security changes in this PR require M1/M8 review before merging.

| Method / path | Input | Success | Access |
|---|---|---|---|
| POST /api/v1/auth/register | email, password, display_name | 201 User | Public, customer only |
| POST /api/v1/auth/login | email, password | 200 Session | Public; four existing roles |
| GET /api/v1/auth/csrf | refresh cookie | csrf_token | Same-site browser |
| POST /api/v1/auth/refresh | refresh cookie + X-CSRF-Token | 200 Session, rotated cookie | Live refresh session |
| POST /api/v1/auth/logout | cookie + X-CSRF-Token if cookie exists | logged_out: true | Current session; repeatable |
| GET /api/v1/auth/me | Bearer access token | Existing identity DTO | Four roles |
| GET /api/v1/membership/profile | Bearer access token | User | Caller only |
| GET /api/v1/users | page >= 1, page_size 1..100 | items, total, page, page_size | Admin |
| POST /api/v1/users | registration fields + role | 201 User | Admin |
| PATCH /api/v1/users/{id}/role | role, version >= 1 | User | Admin |
| PATCH /api/v1/users/{id}/status | is_active (bool), version >= 1 | User | Admin |

User: id, email, display_name, role, is_active, version. Session: access_token,
token_type, expires_in, csrf_token, user. No endpoint returns password_hash or a
refresh token in JSON. Secret input fields are marked as passwords in OpenAPI.
Password validation: minimum 12 characters, maximum 72 UTF-8 bytes. Display name:
1..80 characters after trimming. Email is validated and stored case-folded; a
database unique constraint prevents duplicate normalized addresses. Registration
rejects extra role/status/version fields. Role values are customer/waiter/manager/admin.

Errors: 401 for invalid/missing authentication, 403 for wrong role/origin/CSRF,
404 for missing account, 409 for duplicate email/stale version/last-admin removal,
422 for input validation, 429 for excess login/registration attempts. Quote request_id
when reporting an unexpected error. Credential failures use one public message.

## Sessions and browser integration

Access tokens use existing PyJWT/HS256 helpers, with sid and auth_version claims.
Every shared role guard checks the live account, role, auth version, session expiry
and revocation. Default access lifetime is 60 minutes; refresh lifetime is 7 days
(`APP_REFRESH_TOKEN_EXPIRE_DAYS`, bounded 1..30). A session's absolute expiry is not
extended by refreshing. Revoked or expired sessions reject access even if JWT exp
has not yet passed. A request already authorized before revocation may finish.

Refresh cookies: `restaurant_refresh`, HttpOnly, SameSite=Strict,
Path=/api/v1/auth; Secure in production. The token is a random 48-byte value,
stored only as SHA-256 digest in MySQL. Login/refresh returns an HMAC-bound CSRF
value for the frontend to send in X-CSRF-Token. Page reload obtains that value
through GET /auth/csrf, then refreshes. Origin must match the explicit CORS
allow-list or the same-site API origin, and Sec-Fetch-Site=cross-site is refused.
Requests without Origin still require the CSRF header for cookie mutations.
Login/register reject untrusted browser origins as well.

Refresh rotation remembers old token digests until session expiry. Reusing an old
token revokes the whole session; it cannot create another valid successor. The
frontend shares one refresh promise to prevent duplicate rotations. Logout
revokes only its current session and deletes the cookie; role/status changes
revoke all affected user's sessions. Do not store tokens in URLs or browser storage.

Registration/login are limited to 5 requests/minute per source IP using slowapi's
memory backend. Do not trust arbitrary X-Forwarded-For headers. A multi-worker
production deployment must configure a shared rate-limit backend before relying
on a global limit; this prototype's default limiter is per process.

## Persistence and concurrency

New migration `0002` follows existing `0001`; existing migrations are untouched.
It adds users, auth_sessions, used_refresh_tokens, auth_policy_lock (seed id=1).
It creates missing audit_logs without replacing an existing audit table. Downgrade
removes the four auth tables and deliberately **retains all audit history**.
The Alembic environment now imports existing review, audit and membership models.

All auth writes first SELECT auth_policy_lock id=1 FOR UPDATE, then read/modify
the target rows and commit. This serializes the small prototype's auth writes,
including first-admin creation, refresh, logout and role changes. The single
lock keeps concurrent last-admin checks correct under the existing MySQL
REPEATABLE READ setting; no shared isolation setting is changed. Password hashing
and login verification happen before that lock. Reads do not hold the lock.
User version detects stale admin forms; role/status changes and their audit row
commit together. An audit failure rolls back account changes and session revocation.
MySQL 8.0.12 parses but does not enforce CHECK constraints (enforcement begins at
8.0.16). Role/version validation remains in the application; do not describe the
older server as enforcing these CHECKs. Unique indexes and InnoDB locks still apply.

Member4 should reuse users.id; do not introduce a second user table or another
login endpoint. Points/tier/coupon calculations remain a separate application
service and are not represented by placeholder balances here.

## Permission boundaries

Public registration creates customers only. Administrators create other roles,
list accounts and change role/status. All four roles can view only their own
profile through the profile endpoint. Existing require_staff/review/analytics
guards retain their explicit role lists and now validate sessions in the app.
There is no implicit role inheritance. Unmounted staff/reservation prototype
routers and their business ownership checks remain with those module owners;
this change does not claim their full integration is complete.
