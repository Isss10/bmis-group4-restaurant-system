# OWASP Top 10 (2021) Hardening Status

**Scope:** backend `src/` and deployment `deploy/`.
**Audience:** the group, and whoever assesses Objective (f).
**Last verified:** 2026-11-14, against `main` at `14df591` (PRs #13–#18 merged).
The membership-auth PR #10 landed after the previous revision and closes A01 and
most of A07; this revision re-checks every row against the current tree rather
than carrying the 2026-11-06 claims forward.

Every row below states **where the control lives** and **how it was verified**.
Nothing here is aspirational: the ✅ rows were confirmed by running the code or
reading the exact file, and the ❌ rows are known gaps with an owner and a date.

---

## Summary

| # | OWASP 2021 category | Status | Primary control |
|---|---|---|---|
| A01 | Broken Access Control | ✅ Done | staff, reservation and review routers all carry an auth dependency; reservation and review derive the actor from the token and reject a body-supplied id that disagrees |
| A02 | Cryptographic Failures | ✅ Done | bcrypt cost 12; secrets excluded from repr and dumps; HSTS in production |
| A03 | Injection | ✅ Done | SQLAlchemy ORM throughout; no interpolated SQL in `src/` |
| A04 | Insecure Design | ✅ Done | Envelope + frozen error contract merged to `main` (#13); docs disabled in production |
| A05 | Security Misconfiguration | ✅ Done | Production boot refuses weak secrets and wildcard CORS; docs disabled in production |
| A06 | Vulnerable & Outdated Components | ✅ Done | `pip-audit --strict` and Bandit in CI on every pull request |
| A07 | Identification & Authentication Failures | ⚠️ Partial | login endpoints live and rate-limited (`5/minute` on register and login); **review submission still has no limit, which FR-REV-04 requires** |
| A08 | Software & Data Integrity Failures | ✅ Done | Alembic migrations only; real chain now runs in CI against MySQL 8; auto-discovered migration-completeness guard |
| A09 | Security Logging & Alerting Failures | ⚠️ Partial | `record_audit()` is now called by the membership service; **reservation, order-status and review-moderation mutations still write no audit row** |
| A10 | Server-Side Request Forgery | ➖ Not applicable | No outbound URL fetching anywhere in `src/` |

**Net position:** 7 fully hardened (A01–A06, A08), 2 partial with named gaps
(A07, A09), 1 not applicable (A10). The two ⚠️ rows are the work that remains;
see [Open gaps](#open-gaps).

---

## A01 — Broken Access Control ✅

**What exists**

- `src/common/security.py` defines `require_roles(*roles)` returning a FastAPI
  dependency, plus pre-built role gates (`require_staff`, `REVIEW_MODERATORS`,
  `ANALYTICS_VIEWERS`).
- It refuses to be called with zero roles (`"require_roles() needs at least one
  role, otherwise it permits nobody"`) — an empty allow-list can never silently
  mean "everyone".

**Status — every writing router is now guarded**

Re-verified against `main` at `14df591` by reading each router and by the
committed OpenAPI document:

| Router | Mounted at | Auth dependency | Verdict |
|---|---|---|---|
| `routers/staff.py` | `/api/v1/staff/*` (4 routes) | `Depends(require_staff())` on all four | ✅ guarded |
| `routers/reservation.py` | `/api/v1/reservations`, `/{id}/cancel` | `Depends(require_roles(Role.CUSTOMER))` | ✅ guarded |
| `routers/review.py` | `/api/v1/reviews/` | `Depends(require_roles(Role.CUSTOMER))` | ✅ guarded |

The two customer routers were the gap in the previous revision; PR #10 closed it.
Both now derive the actor from the token, not from the request body: the
reservation handler rejects a payload whose `user_id` disagrees with the token's
`sub` (`permission_denied()`), and the review handler rejects a `customer_id`
that disagrees with the token's `sub`. The old "caller can post a review as
anyone" exposure is gone — the body field is now validated *against* the
authenticated identity rather than trusted.

**What is intentionally public** (confirmed via the committed `openapi.json`, the
paths carrying no `security` block): `/`, `/api/v1/health`, the five
`/api/v1/auth/*` endpoints (register, login, logout, refresh, csrf — these are
the entry points, they cannot require a token), and
`/api/v1/reviews/dishes/ranking` (a public read-only leaderboard). Every path
that *writes* business data now carries an auth dependency.

**Rule for every module owner:** a route that reads or writes business data must
declare an auth dependency. Back-office routes use `dependencies=[Depends(require_staff)]`
or a narrower gate; customer routes use `Depends(get_current_token)` and derive
the actor from the token, **never** from a client-supplied id field.

**How to verify yours:** open `http://localhost:8000/openapi.json` after merging
and confirm every path that mutates data carries a `security` block. An
authenticated API whose OpenAPI document has no `security` entries is the classic
sign of a missing gate.

---

## A02 — Cryptographic Failures ✅

| Control | Where | Verified |
|---|---|---|
| Passwords hashed with bcrypt, **cost ≥ 12** | `security.py`: `_BCRYPT_MIN_ROUNDS = 12`, passed as `bcrypt__rounds` | Unit-tested in `tests/unit/test_security.py` |
| Passwords above bcrypt's 72-byte limit rejected rather than silently truncated | `_BCRYPT_MAX_BYTES = 72` with an explicit `ValueError` | Same |
| Weak/legacy hashes detected so users can be re-hashed on next login | `password_needs_rehash()` | Same |
| DB password and JWT secret excluded from logs **and** serialisation | `config.py`: `Field(default="", repr=False, exclude=True)` | `repr=False` alone is insufficient — `model_dump()` would still emit the raw value. Both flags are set, which is why this is listed as done |
| JWT signed with a pinned algorithm | `jwt_algorithm = "HS256"`; verification passes `algorithms=[cfg.jwt_algorithm]` | Pinning the accepted algorithm list is what prevents the `alg=none` downgrade |
| Access tokens expire | `access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)` | The `ge=1` bound makes a non-expiring token impossible to configure |
| Secrets never committed | `alembic.ini` stores no connection string; `env.py` resolves the URL from environment | File header documents this deliberately |

---

## A03 — Injection ✅

- `git grep -E "execute\((f\"|f')"` over `src/` returns **nothing**: there is no
  string-interpolated SQL anywhere in the backend.
- All persistence goes through SQLAlchemy 2.0 ORM mapped columns and bound
  parameters (`src/data/database.py`, `src/data/schema/`).
- Request bodies are Pydantic models, so type coercion happens before any value
  reaches a query.
- `src/common/audit.py` stores caller-supplied JSON via a `JSON` column, not via
  string concatenation.

**Remaining surface:** the frontend. PR #12 (merged) added the real Vue 3 + Vite
+ TypeScript SPA under `frontend/`, and PR #18 added the customer ordering UI
(category filter, cart, order submission); PR #10 added a membership client under
`src/presentation/membership/`. The static prototype at
`src/presentation/web/index.html` is now superseded. The XSS rule still applies to
all three clients: avoid `v-html` with user-supplied content — that reintroduces
stored XSS regardless of how clean the backend is. The committed clients were not
audited line-by-line in this revision; a `v-html` sweep over `frontend/` and
`src/presentation/membership/` is outstanding (owner: M5).

---

## A04 — Insecure Design ✅

**What exists (now on `main`, merged in PR #13)**

- A frozen response-envelope contract and a single error vocabulary live in
  `src/common/envelope.py` and `src/common/errors.py`, both confirmed present on
  `main` (`git ls-tree origin/main src/common/`).
- Exception text is deliberately **not** returned to clients: `middleware.py`
  documents that `str(exc)` is excluded, so a 500 says "Internal Server Error"
  and nothing more. Stack traces stay in the logs, correlated by `X-Request-ID`.
- Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are **disabled in
  production** — `docs_url="/docs" if not cfg.is_production else None`. An
  unauthenticated attacker should not get a machine-readable map of the API.
- `src/data/database.py` documents the isolation level (READ COMMITTED) and the
  three-layer locking assumptions the concurrency design depends on, rather than
  leaving them implicit.

**Why this was previously ⚠️ and is now ✅:** the envelope and error contract sat
stranded on `feature/contract-alignment` with no PR open as of the last revision.
That PR is now #13, merged. Every module therefore shares one response shape and
one 5-digit error vocabulary instead of inventing its own.

**Remaining design-level gap (tracked under A01, not A04):** the reservation and
review routers do not authenticate the caller, and review takes the actor's
identity from the request body. That is an access-control defect (A01) rather
than a missing-design one — the contract and the role matrix exist; the two
routers simply have not adopted them yet.

---

## A05 — Security Misconfiguration ✅

`src/common/config.py` validates the configuration at construction time and
**refuses to boot in production** if any check fails (`raise ValueError`):

- `APP_JWT_SECRET_KEY` must not be in the weak-secret set
  (`"", "changeme", "change-me", "secret", "password", "todo", "xxx"`)
- `APP_JWT_SECRET_KEY` must be at least 32 characters
- `APP_DB_PASSWORD` must not be a weak secret
- `APP_CORS_ORIGINS` must not contain `*` in production

Failing closed at startup is what makes these real. A warning in a log gets
ignored; a container that will not start does not.

**Response hardening** (`middleware.py`, applied to every response):

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
X-XSS-Protection: 0                      # deliberate: the legacy filter causes
                                         # more bugs than it prevents
Strict-Transport-Security                # production only: sending it on a local
                                         # HTTP dev server would pin the browser
                                         # to HTTPS for a domain that has none
Content-Security-Policy                  # default-src 'self'; object-src 'none';
                                         # frame-ancestors 'none'
del response.headers["Server"]           # do not advertise the stack
```

**Container hardening** (`deploy/docker/Dockerfile`):

- Multi-stage build (`builder` → `runtime`), so build tooling and wheels never
  ship in the final image
- `--no-cache-dir` on pip and `--no-install-recommends` on apt, to keep the
  image surface small
- Dedicated non-root user: `groupadd --system --gid 1001 appuser` then
  `USER appuser`
- `HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3`, so
  the orchestrator can detect a dead container
- `alembic.ini` is copied explicitly with a comment explaining why — it lives
  outside `src/` and the container exits immediately without it

**Deployment** (`deploy/docker/docker-compose.yml`) runs
`alembic upgrade head` as part of the API container's startup command, so the
schema always matches the deployed code.

> **Note for whoever assesses this:** the Docker image cannot be built on a
> Windows machine without Docker installed. The CI `docker-build` job does build
> it, and it currently passes — that is the authoritative verification, not a
> local build.

---

## A06 — Vulnerable & Outdated Components ✅

`.github/workflows/ci.yml` runs on **every** pull request:

- `pip-audit --strict -r requirements.txt -r requirements-dev.txt` — fails the
  build on any known-vulnerable dependency. `--strict` matters: without it,
  advisory lookups that fail silently pass.
- Bandit in two steps: a report artefact with `--exit-zero` (informational),
  then `bandit -r src -c pyproject.toml --severity-level medium` which **does**
  fail the build. Currently clean at medium and above.
- Ruff lint + format check, and mypy over `src/`.
- A dependency-caching setup keyed on the requirements files.
- The `hygiene` job blocks committed secrets and `.env` files and scans tracked
  files for hardcoded credentials, so a leaked key fails the build rather than
  sitting in history unnoticed.

Verified by CI on every pull request against `main`; the green run at `14df591`
covers `ruff check`, `ruff format --check`, `mypy src`, Bandit at medium and
above, and `pip-audit --strict`. The unit suite collects 318 tests at this
baseline (up from 235 at the previous revision, as the membership module's tests
landed). Local re-runs from the maintainer's `.venv-diag` have matched CI on every
run so far.

> The project `.venv` on the maintainer's machine is blocked by the OS
> application-control policy, so local verification runs from a rebuilt
> environment (`.venv-diag`, Python 3.14 with the pinned requirements). The CI
> jobs on Python 3.11 remain the authoritative gate; local results have matched
> them on every run so far.

---

## A07 — Identification & Authentication Failures ⚠️

**What exists**

- JWT access tokens with an explicit algorithm and expiry (see A02).
- Verification pins `algorithms=[cfg.jwt_algorithm]`, blocking the `alg=none`
  bypass.
- `require_roles()` enforces a minimum role per route (see A01).
- Failed logins are auditable via `ACTION_LOGIN_FAILURE`.
- **Login endpoints are live.** PR #10 added `/api/v1/auth/register`, `/login`,
  `/refresh`, `/logout` and `/csrf` in `routers/membership.py`, mounted through
  `install_membership(app)`.
- **Rate limiting is wired.** `routers/membership.py` builds a `slowapi`
  `Limiter(key_func=get_remote_address)` and `install_membership` attaches it
  (`app.state.limiter = limiter`), registers the `RateLimitExceeded` handler, and
  honours the `rate_limit_enabled` setting. `@limiter.limit("5/minute")` guards
  both `register` and `login`, so the credential-stuffing surface is throttled.

**The gap — review submission is still not rate-limited**

`config.py` defines the limits and the `Limiter` is attached to the app, but the
limit decorators are only on the two membership auth routes. **`POST
/api/v1/reviews/` carries no limit.** FR-REV-04 requires review submission to be
rate-limited (default 5/minute per user) with limit hits recorded, and the
`rate_limit_review = "5/minute"` setting already exists for exactly this — it is
configured but not applied to the review router.

```python
# config.py — the limits that exist
rate_limit_default: str = "200/minute"
rate_limit_review:  str = "5/minute"
rate_limit_enabled: bool = True
```

The fix is local: the review router needs `@limiter.limit("5/minute")` on its
submission handler (the limiter instance is already on `app.state`). Until then a
single caller can flood `POST /api/v1/reviews/`, which is both a spam vector and
a way to distort a dish's ranking — the very thing FR-REV-04 exists to stop.

**Why the limits are per-route rather than global:** a blanket `200/minute`
throttles an attacker no more than a legitimate customer. Login needs something
far tighter (a few attempts per minute per IP), and review submission needs the
`5/minute` limit that Objective (c) specifies.

---

## A08 — Software & Data Integrity Failures ✅

- Schema changes go **only** through Alembic migrations
  (`src/data/migration/versions/`). `Base.metadata.create_all()` is used in
  tests, never in deployment.
- `deploy/docker/docker-compose.yml` runs `alembic upgrade head` at container
  start, so a deployed image cannot run against a schema it did not create.
- `tests/unit/test_migration_completeness.py` runs the real migration chain
  against a scratch SQLite database and compares the result with the mapped
  models in both directions — a model with no migration fails the unit job, and
  a stale migration that no model declares also fails. It also asserts a single
  migration head, that every expected table is actually discovered, and that the
  chain survives up → down-to-base → up.
- **Models are discovered automatically**, not from a hand-maintained list.
  `src/data/model_discovery.py` walks `src/` and imports every module, so
  `env.py` (Alembic autogenerate) and the guard test share one discovery path
  and cannot disagree. Adding a model now needs no edit anywhere. Import
  failures raise rather than skip: a model that cannot be imported is invisible
  to autogenerate, which then emits a migration that **drops** its table.
- **CI now runs the real migration chain against MySQL 8** (the `test-integration`
  job), asserting every declared table exists and that the chain downgrades and
  re-upgrades. Before this, the word "alembic" appeared in `ci.yml` only in a
  comment — no job ever executed one, which is why the two defects below reached
  `main` with a green pipeline. A non-blocking `alembic check` drift step sits
  alongside it; promote it to blocking once a run shows a clean baseline.
- The committed `docs/api/openapi.json` was last re-verified against the running
  app on 2026-11-06 at `2876fa2`. **It is now stale and must be re-exported
  before this claim is trusted again:** PRs #10 and #18 added the auth and
  membership routes after that check, so the committed document and the running
  app have diverged. As of 2026-11-14 the committed file lists 20 paths including
  the `/api/v1/auth/*` and membership endpoints, but it has not been diffed
  against a fresh export at `14df591`, and `/api/v1/orders` and
  `/api/v1/analytics` are absent because those routers are not mounted (gap 4).
  Re-export with `python scripts/export_openapi.py` and re-diff. One caveat worth
  knowing: the committed blob is LF while a regeneration on Windows writes CRLF,
  so a raw hash comparison differs by line endings only — regenerate on Linux/CI,
  or normalise before hashing. There is **no CI check** for this, so the two drift
  the moment someone adds a route without re-exporting; consider adding a diff
  check to the `hygiene` job (FR-XX-04 requires the re-export after every route
  change).
- The `hygiene` job blocks committed secrets and `.env` files, and scans tracked
  files for hardcoded credentials.
- The `hygiene` job validates pull-request titles and commit messages against
  the conventional commit format, and blocks large files that belong outside Git.

**Why the guard exists:** two models shipped with no migration, six days apart —
`audit_logs` (in `src/common/audit.py`) and `reservations` (merged in PR #3).
Every write then raised `no such table` on a migrated database, but the suite
stayed green because `conftest.py` builds its schema with `create_all()` and no
CI job ran a migration. The first guard missed `reservations` because model
discovery was a hand-maintained import list that omitted it — the same root cause
that hid the model from autogenerate. Discovery is now automatic, and the guard
was mutation-tested: deleting either migration fails the suite, and making a
model inherit from a different `Base` (invisible to discovery) fails it too.

---

## A09 — Security Logging & Alerting Failures ⚠️

**What exists**

`src/common/audit.py` provides a **queryable** audit trail, not just log lines.
Log files rotate and are lost; a manager asking "who changed this reservation's
status last Tuesday?" needs rows that survive restarts.

- `AuditLog` model: 14 columns, `audit_logs` table created by migration `0002`.
- `record_audit()` appends **inside the caller's transaction** and does not
  commit. That atomicity is the point: a trail recording a change that never
  happened is worse than none, and a change with no trail is what we are
  preventing.
- **Credential redaction** is unconditional and recursive. `_REDACT_KEY_FRAGMENTS`
  covers `password`, `passwd`, `pwd`, `secret`, `token`, `authorization`,
  `credential`, `private_key`, `api_key`, `apikey`, `cvv`, `card_number`,
  `session_id`, `cookie`. Matching is case-insensitive substring, so
  `user_password` is caught too. Values are replaced with `[REDACTED]`.
  Verified: `details={"password": "x"}` persists as
  `{"password": "[REDACTED]"}` while non-sensitive keys such as `reason` are
  preserved.
- `user_agent` is truncated to 512 characters before storage.
- `diff_dicts()` stores only changed fields, so the table does not bloat.
- `serialise_for_audit()` degrades unknown objects to `repr()` instead of
  raising — an audit failure must never abort the business transaction it
  describes.
- Role is **snapshotted** per row rather than joined from `users`, so history
  stays correct after someone's role changes.
- Composite indexes cover the two real query shapes: `ix_audit_actor_time`
  (who did what) and `ix_audit_entity` (who touched this object), plus
  `ix_audit_action_time` for action-centric review.
- Every row is also mirrored to the application log with `request_id`, so
  operations can tail it live and correlate it with request logs.
- Read-only operations are deliberately **not** audited; that would bury the
  signal in noise.

**The gap — only the membership module writes audit rows so far**

Re-verified on 2026-11-14 against `main` at `14df591`: `git grep -n
"record_audit(" -- src` now finds **two call sites, both in
`src/application/membership/service.py`** (admin bootstrap and the `_audit`
helper used on role/status changes). The previous revision's "not a single call
site" is no longer true — PR #10 wired the membership module, so user and role
mutations are audited.

The gap has narrowed but not closed. FR-XX-03 requires *back-office state
changes* — reservation status, order status, review moderation, points, coupons —
to be audit-logged with before/after snapshots, and names the owner as **M1 +
module owners**. Of those, none is wired yet:

| Mutation | Audit action constant exists? | Wired? |
|---|---|---|
| user / role change | `ACTION_USER_ROLE_CHANGED` | ✅ membership service |
| reservation status change | `ACTION_RESERVATION_STATUS_CHANGED` | ❌ not called |
| order status change | `ACTION_ORDER_STATUS_CHANGED` | ❌ not called |
| review moderation | `ACTION_REVIEW_MODERATED` | ❌ not called |
| points adjustment | `ACTION_POINTS_ADJUSTED` | ❌ not called |
| coupon issue / redemption | `ACTION_COUPON_ISSUED` / `_REDEEMED` | ❌ not called |

The action constants are all defined in `audit.py`; what is missing is the call
at each mutation point. The infrastructure is finished and unit-tested (30 tests
in `tests/unit/test_audit.py`, 97.4% coverage of `audit.py`).

The two staff mutations are the natural next targets: `PATCH
/api/v1/staff/reservations/{id}` and `PATCH /api/v1/staff/orders/{id}`. Their
handlers still return placeholder data (see A09 note below and chapter 7 of the
report), so wiring audit there should happen together with connecting them to the
real services — otherwise we would be auditing a mutation that does not mutate
anything.

**Verified end-to-end on 2026-10-25 (infrastructure):** `alembic upgrade head`
creates the table with all 14 columns and all 9 indexes; `record_audit()` writes
and reads back correctly; redaction confirmed; `downgrade` to base removes the
table cleanly and re-`upgrade` reproduces it identically. This proves the
mechanism works. The membership call sites now also prove it is reachable from a
real service; the remaining mutations do not yet exercise it.

---

## A10 — Server-Side Request Forgery ➖ Not applicable

No code path in `src/` fetches a URL supplied by a client. There is no
webhook receiver, no URL preview, no image-from-URL importer, no outbound HTTP
client. Verified by inspection of the dependency set and `src/`.

**This row becomes applicable** the moment anyone adds: importing a menu from a
URL, fetching a user-supplied avatar, calling a payment gateway with a
client-provided callback URL, or any webhook. If that happens, validate the
scheme against an allow-list (`https` only), resolve and block private/link-local
ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
`169.254.0.0/16`, `::1`, `fc00::/7`) *after* DNS resolution to survive a
rebinding attack, and disable redirects.

---

## Open gaps

Four items, each with an owner and a date. Ordered by how much they block.

| # | Gap | Blocks | Owner | Target |
|---|---|---|---|---|
| 1 | **Review submission is not rate-limited.** The `Limiter` is attached to the app and guards register/login, but `POST /api/v1/reviews/` has no `@limiter.limit`, despite `rate_limit_review = "5/minute"` already being configured. A caller can flood reviews and distort a dish's ranking. | A07, FR-REV-04 | **Member9** | with the review module's next pass |
| 2 | **Audit logging wired only in membership.** `record_audit()` is called by the membership service but by no other module. Reservation status, order status, review moderation, points and coupon mutations write no audit row, so FR-XX-03 is unmet for every back-office change outside membership. The two staff mutation endpoints are the next targets, but should be wired together with connecting them to real services. | A09, FR-XX-03 | **M1** + module owners | with each module's service wiring |
| 3 | **The concurrency test has never executed.** `tests/concurrency/test_concurrent_booking.py` (merged in PR #11) declares no `pytest` marker, so the CI job's `-m "integration or concurrency"` selection deselects it; it is never collected. It would also fail if collected — it POSTs to a non-existent `/reservations/book` route with the wrong payload and no token, and asserts on transport status rather than the envelope code. Underneath it, the reservation service has no conflict detection and the table has no `version` column or unique constraint, so a concurrent second booking cannot fail yet. This is the core Objective (d) deliverable and the headline demo/report evidence. | Objective (d), NFR-01 | **M8 + M2** (schema/service), **M7** (test) | 30 Nov |
| 4 | **Two contracted routers are declared but not mounted.** `routers/ordering.py` and `routers/analytics.py` do not exist, so `/api/v1/orders` and `/api/v1/analytics` are in the registry but never mounted — the tolerant loader skips them at debug level. Not an OWASP gap, but it means the OpenAPI surface and the running app disagree, which undermines the A01/A08 verification method (an endpoint can be documented and absent). | FR-ORD, FR-ANA, A08 | **M5/M2** (ordering), **M6** (analytics) | 30 Nov |

**Closed since the last revision:**

- **Reservation and review routers authenticated (was gap 1).** PR #10 added
  `Depends(require_roles(Role.CUSTOMER))` to both, and each now validates a
  body-supplied id against the token's `sub`. A01 moved from ⚠️ to ✅.
- **Rate limiting wired for auth (part of was gap 3).** PR #10 attached the
  `slowapi` `Limiter` to the app and limited register/login to `5/minute`. The
  remaining piece — review submission — is now gap 1 above.
- **Contract branch merged (earlier revision).** `feature/contract-alignment`
  landed as PR #13; A04 moved from ⚠️ to ✅.
- **Staff routes authenticated (earlier revision).** PR #4's four staff routes are
  mounted and guarded by `require_staff()`.
- **Coverage floor raised.** `pyproject.toml` sets `fail_under = 80`; the unit
  suite cleared it at the previous baseline. Treat 80 as a ratchet: raise it as
  the suite comfortably clears higher numbers, never lower it. The
  `test-integration` job passes `--cov-fail-under=0` explicitly so an empty
  integration directory exits 5 (no tests collected) rather than 1.

---

## How to re-verify this document

Every claim above is checkable with commands that touch nothing:

```bash
# A03 - no interpolated SQL
git grep -nE "execute\((f\"|f')" -- src

# A07 - rate limiting wired?
git grep -nE "slowapi|Limiter" -- src
# Expected at 14df591: hits in src/presentation/api/routers/membership.py (the
# Limiter build and the two @limiter.limit decorators on register/login). The
# review router has NO hit yet — that is gap 1.

# A01 - which routers carry an auth dependency?
git grep -nE "require_staff|require_roles|get_current_token" -- src/presentation/api/routers
# cross-check against the mounted table: every path that writes must have a security block
python -c "import json; d=json.load(open('docs/api/openapi.json')); \
print([p for p,v in d['paths'].items() for m in v.values() if 'security' not in m] or 'all guarded')"
# Expected output at 14df591 (all intentionally public — no write endpoint is bare):
#   ['/', '/api/v1/auth/csrf', '/api/v1/auth/login', '/api/v1/auth/logout',
#    '/api/v1/auth/refresh', '/api/v1/auth/register', '/api/v1/health',
#    '/api/v1/reviews/dishes/ranking']
# '/' and '/health' are the service index and liveness probe; the auth endpoints
# are the entry points (they cannot require a token); dishes/ranking is a public
# read-only leaderboard. If a WRITE path (reservations, reviews/, staff, orders,
# membership) ever appears in this list, it is a regression — re-add its gate.

# A09 - does anything actually write an audit row?
git grep -n "record_audit(" -- src
# Expected at 14df591: two real call sites in
# src/application/membership/service.py (plus the definition in common/audit.py
# and doc/comment mentions). Every other mutation point is still unwired — gap 2.

# A08/A09 - migration chain is complete and reversible
pytest tests/unit/test_migration_completeness.py -v

# A02/A06 - all quality gates
ruff check src tests && ruff format --check src tests && mypy src
black --check src tests
bandit -r src -c pyproject.toml --severity-level medium
pytest tests/unit -m "not integration and not concurrency and not slow" --cov=src

# A08 - the archived API document vs the running app. NOTE: as of 14df591 the
# committed openapi.json is STALE (PRs #10 and #18 added routes after the last
# export). This diff is expected to be non-empty until someone re-exports.
# Regenerate on Linux/CI; a Windows regeneration differs by line endings only.
python scripts/export_openapi.py --output /tmp/openapi-check.json
diff /tmp/openapi-check.json docs/api/openapi.json

# A09 - the table really gets created by migrations
alembic -x url=sqlite:////tmp/probe.db upgrade head
```

If a row says ✅ and its command fails, **the row is wrong** — fix the row or
fix the code, and say which. A hardening document that cannot be re-checked is
just an opinion.
