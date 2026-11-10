# Membership authentication API — Member10 / T4

Implementation and integration updated on 8 November 2026 for the 23 November deadline.
The proposal's full T4 deadline remains 23 November; Member4 owns loyalty rules.
Generated request/response schemas: [openapi.json](openapi.json).

## Contract and compatibility

This implementation is rebased on main `963c70e`, including its frozen unified
response envelope. All successful payloads below live in `data`:

```json
{"code":0,"message":"ok","data":{},"request_id":"req_example","timestamp":"2026-11-08T10:00:00Z"}
```

Errors use the same flat keys with `data: null` and optional
`errors: [{"field":"...","detail":"..."}]`. Missing Bearer credentials use
30001; invalid, expired or revoked credentials use 30002; denied role, ownership,
origin or CSRF use 30003; missing accounts use 40001; stale versions use 20004.
Input/account rule validation uses existing 10001 (HTTP 422 for malformed input,
409 for duplicate email/last-admin protection). Rate limiting keeps HTTP 429 and
Retry-After with existing code 10001 and a request detail; the frozen catalogue
has no separate assigned rate-limit code. No new business codes are invented.

`GET /api/v1/auth/me` retains user_id, role, token_id, expires_at inside `data`.
Tokens must identify a live database session; old hand-minted tokens without
`sid` and `auth_version` are rejected. Clients obtain tokens from login.
Shared API/schema/security changes require M1/M8 review before merging.

| Method / path | Input | Success | Access |
|---|---|---|---|
| POST /api/v1/auth/register | email, password, display_name | 201 User | Public, customer only |
| POST /api/v1/auth/login | email, password | 200 Session | Public; four existing roles |
| GET /api/v1/auth/csrf | refresh cookie | csrf_token | Same-site browser |
| POST /api/v1/auth/refresh | refresh cookie + X-CSRF-Token | 200 Session, rotated cookie | Live refresh session |
| POST /api/v1/auth/logout | cookie + X-CSRF-Token if cookie exists | logged_out: true | Current session; repeatable |
| GET /api/v1/auth/me | Bearer access token | Existing identity DTO | Four roles |
| GET /api/v1/membership/profile | Bearer access token | User | Caller only |
| GET /api/v1/users | page >= 1, page_size 1..100 | items, total, page, page_size, total_pages | Admin |
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

New migration `0004_add_membership_auth.py` has revision 0004 and down_revision
0003, following main's 0001 reviews, 0002 audit and 0003 reservations. Existing
migrations are unchanged. There is exactly one Alembic head. It adds only users,
auth_sessions, used_refresh_tokens and auth_policy_lock (seed id=1). Existing
main databases upgrade directly with `alembic upgrade head`; no stamp or rebuild
is needed. Downgrading **0004 to 0003** removes auth tables while preserving
main's reservations and audit history. A deliberate full downgrade to base also
runs the older revisions, which delete their own tables and data. Back up before
any destructive downgrade. Automatic model discovery remains main's implementation.

If a disposable local database already applied the earlier unmerged PR's 0002
membership migration, do not stamp it as main's unrelated 0002. Use a fresh
isolated development database and apply the current chain; retain/backup the old
database until its data is no longer needed. This PR does not rewrite database history.

All auth writes first SELECT auth_policy_lock id=1 FOR UPDATE, then read/modify
the target rows and commit. This serializes the small prototype's auth writes,
including first-admin creation, refresh, logout and role changes. The single
lock keeps concurrent last-admin checks correct under the existing MySQL
READ COMMITTED setting; no shared isolation setting is changed. Password hashing
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
There is no implicit role inheritance. Mounted reservation creation/cancellation
and review submission require customer. Reservation creation derives user_id from
the verified subject; the optional legacy user_id must match. Cancellation checks
ownership after locking the row in the same transaction as its update. Review
submission rejects a customer_id that differs from the token before calling the
review service. Anonymous calls fail 401/30001; wrong roles/ownership fail 403/30003.
Revoked sessions also fail these routes and every mounted staff operation.

Review order eligibility remains M9/M5's business dependency: the current
OrderServiceStub returns True, so these permission tests do not prove a completed
order exists. Member4's loyalty API is not mounted in main yet. The handoff and
actual acceptance evidence are recorded in
[Member10 November 23 delivery](../proposal/PROJECT_UPDATE_MEMBER10_NOV23.md).
