# OWASP Top 10 (2021) Hardening Status

**Scope:** backend `src/` and deployment `deploy/`.
**Audience:** the group, and whoever assesses Objective (f).
**Last verified:** 2026-11-06, against `main` at `2876fa2` (PRs #13, #14, #15, #16 merged).

Every row below states **where the control lives** and **how it was verified**.
Nothing here is aspirational: the ✅ rows were confirmed by running the code or
reading the exact file, and the ❌ rows are known gaps with an owner and a date.

---

## Summary

| # | OWASP 2021 category | Status | Primary control |
|---|---|---|---|
| A01 | Broken Access Control | ⚠️ Partial | `require_staff()` now guards all four staff routes; **reservation and review routers still declare no auth dependency** |
| A02 | Cryptographic Failures | ✅ Done | bcrypt cost 12; secrets excluded from repr and dumps; HSTS in production |
| A03 | Injection | ✅ Done | SQLAlchemy ORM throughout; no interpolated SQL in `src/` |
| A04 | Insecure Design | ✅ Done | Envelope + frozen error contract merged to `main` (#13); docs disabled in production |
| A05 | Security Misconfiguration | ✅ Done | Production boot refuses weak secrets and wildcard CORS; docs disabled in production |
| A06 | Vulnerable & Outdated Components | ✅ Done | `pip-audit --strict` and Bandit in CI on every pull request |
| A07 | Identification & Authentication Failures | ⚠️ Partial | JWT issued and verified; **no rate limiting wired** (and no login endpoint on `main` yet) |
| A08 | Software & Data Integrity Failures | ✅ Done | Alembic migrations only; real chain now runs in CI against MySQL 8; auto-discovered migration-completeness guard |
| A09 | Security Logging & Alerting Failures | ⚠️ Partial | `audit_logs` table + `record_audit()` built and tested, **but no module endpoint calls it yet** |
| A10 | Server-Side Request Forgery | ➖ Not applicable | No outbound URL fetching anywhere in `src/` |

**Net position:** 6 fully hardened, 3 partial with named gaps (A01, A07, A09), 1 not applicable.
The three ⚠️ rows are the work that remains; see [Open gaps](#open-gaps).

---

## A01 — Broken Access Control ⚠️

**What exists**

- `src/common/security.py` defines `require_roles(*roles)` returning a FastAPI
  dependency, plus pre-built role gates (`require_staff`, `REVIEW_MODERATORS`,
  `ANALYTICS_VIEWERS`).
- It refuses to be called with zero roles (`"require_roles() needs at least one
  role, otherwise it permits nobody"`) — an empty allow-list can never silently
  mean "everyone".

**The gap**

Status changed materially with PR #13 (merged). Verified against `main` at
`2876fa2` by reading each router and by the generated OpenAPI document:

| Router | Mounted at | Auth dependency | Verdict |
|---|---|---|---|
| `routers/staff.py` | `/api/v1/staff/*` (4 routes) | `Depends(require_staff())` on all four | ✅ guarded |
| `routers/reservation.py` | `/api/v1/reservations`, `/{id}/cancel` | **none** | 🔴 open |
| `routers/review.py` | `/api/v1/reviews/` | **none** | 🔴 open |

So the picture inverted. The staff routes — the ones this document previously
flagged as the exposure — are now mounted *and* guarded: their OpenAPI entries
carry a `security: [{HTTPBearer: []}]` block, and the old `require_staff_roles()`
stub that returned a hardcoded dict has been replaced with the real
`require_staff()` gate (waiter/manager/admin).

The remaining gap is the other two. **`POST /api/v1/reservations` books a table
and `POST /api/v1/reviews/` writes a review, both with no authentication at all**
— any unauthenticated caller can create rows. Per the frozen role matrix (manual
§4.4) both are customer actions, so they need `Depends(get_current_token)` at
minimum, plus the ownership check that FR-REV-01 requires (a customer may only
review a dish they actually ordered, which needs the caller's identity to
enforce server-side — right now nothing reads it). The review router currently
takes `customer_id` from the request body, which means a caller can post a review
as anyone.

**Rule for every module owner:** a route that reads or writes business data must
declare an auth dependency. Back-office routes use `dependencies=[Depends(require_staff)]`
or a narrower gate; customer routes use `Depends(get_current_token)` and derive
the actor from the token, **never** from a client-supplied id field.

**How to verify yours:** open `http://localhost:8000/openapi.json` after merging
and confirm every path carries a `security` block. An authenticated API whose
OpenAPI document has no `security` entries is the classic sign of a missing gate.

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

**Remaining surface:** the frontend. What is on `main` today is a single static
prototype page, `src/presentation/web/index.html` (menu data hardcoded, no API
calls). PR #12 is building the real Vue 3 SPA under `frontend/`; when it lands,
avoid `v-html` with user-supplied content — that reintroduces stored XSS
regardless of how clean the backend is.

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

Verified locally on 2026-11-06 against `main` at `2876fa2`: `ruff check`,
`ruff format --check`, `black --check` (35 files unchanged), `mypy src`
(35 source files, no issues) and the 235-test unit suite all pass.

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

**The gap — rate limiting is configured but not wired**

`config.py` defines the limits:

```python
rate_limit_default: str = "200/minute"
rate_limit_review:  str = "5/minute"
rate_limit_enabled: bool = True
```

and `requirements.txt` pins `slowapi>=0.1.9,<0.2`, which **is installed**. But
`git grep -E "slowapi|Limiter"` over `src/` returns nothing: **no limiter is
attached to the application**, so no endpoint is actually limited.

This is now unblocked. It previously had to wait for `feature/contract-alignment`
to avoid a guaranteed conflict in `main.py`; that branch merged as PR #13, so the
limiter can be wired directly against `main`.

**Note on severity:** there is no login endpoint on `main` yet (only
`GET /api/v1/auth/me`, which verifies an existing token). PR #10 adds
authentication, so the credential-stuffing exposure is *not yet live* — but the
limiter must land with or before #10, not after it.

**Why the limits are per-route rather than global:** a blanket `200/minute`
throttles an attacker no more than a legitimate customer. Login needs something
far tighter (a few attempts per minute per IP), and review submission needs the
`5/minute` limit that Objective (c) already specifies. Note that
`POST /api/v1/reviews/` **is** live on `main` today and is therefore the one
existing endpoint that already needs its limit applied (FR-REV-04).

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
- The committed `docs/api/openapi.json` currently matches the generated document
  **line for line** — re-verified on 2026-11-06 against `main` at `2876fa2` by
  running `python scripts/export_openapi.py` and diffing (653 lines both sides,
  zero differing lines, identical path and schema sets). One caveat worth knowing:
  the committed blob is LF while a regeneration on Windows writes CRLF, so a raw
  hash comparison differs by line endings only. Regenerate on Linux/CI, or
  normalise before hashing, if you want a byte-level check. There is **no CI
  check** for this, so the two can drift the moment someone adds a route without
  re-exporting. Re-export with `python scripts/export_openapi.py` after any route
  change, and consider adding a diff check to the `hygiene` job.
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

**The gap — the trail records nothing, because nothing calls it**

Verified on 2026-11-06: `git grep -n "record_audit" origin/main -- src` returns
**only the definition, its docstring, and two comments explaining a past bug**.
There is not a single call site. No route, service or repository writes an audit
row, so in a deployed system the `audit_logs` table stays permanently empty.

FR-XX-03 in `docs/requirements/REQUIREMENTS.md` requires back-office state
changes (reservation status, order status, review moderation, points, coupons,
roles) to be audit-logged with before/after snapshots, and names the owner as
**M1 + module owners**. The infrastructure is finished and unit-tested
(30 tests in `tests/unit/test_audit.py`, 97.4% coverage of `audit.py`); what is
missing is the wiring at each mutation point.

Two of the four staff mutations are on `main` now and are the natural first
targets: `PATCH /api/v1/staff/reservations/{id}` and `PATCH /api/v1/staff/orders/{id}`.
Their handlers still return placeholder data, so wiring audit there should happen
together with connecting them to the real services — otherwise we would be
auditing a mutation that does not mutate anything.

**Verified end-to-end on 2026-10-25 (infrastructure only):** `alembic upgrade head`
creates the table with all 14 columns and all 9 indexes; `record_audit()` writes
and reads back correctly; redaction confirmed; `downgrade` to base removes the
table cleanly and re-`upgrade` reproduces it identically. This proves the
mechanism works — it does not prove anything is being recorded.

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
| 1 | **Reservation and review routers have no auth dependency.** `POST /api/v1/reservations` and `POST /api/v1/reviews/` are live on `main` and accept writes from any unauthenticated caller. Review also takes `customer_id` from the request body, so a caller can post as anyone. | A01, FR-REV-01 | **Member2** (reservation), **Member9** (review) | before next module merge |
| 2 | **Audit logging not wired.** `record_audit()` is built and tested but has zero call sites; `audit_logs` stays empty in a deployed system. The two staff mutation endpoints are the first targets, but should be wired together with connecting them to real services. | A09, FR-XX-03 | **Member1** + module owners | with each module's service wiring |
| 3 | **Rate limiting not wired.** `slowapi` is installed and limits are configured, but no `Limiter` is attached to the app. No longer blocked (the contract branch it had to wait for is merged). Must land with or before PR #10's login endpoint; `POST /api/v1/reviews/` is already live and already needs its `5/minute` limit. | A07, FR-REV-04 | **Member1** | before PR #10 merges |
| 4 | **No integration or concurrency tests.** `tests/integration/` and `tests/concurrency/` contain only `.gitkeep`. The concurrency test that proves only one of many simultaneous bookings succeeds is the core Objective (d) deliverable and the headline demo/report evidence. | Objective (d), NFR-01 | **Member4 + Member7** | 30 Nov |

**Closed since the last revision:**

- **Contract branch merged (was gap 1).** `feature/contract-alignment` landed as
  PR #13. The envelope, error contract and new router loader are on `main`; A04
  moved from ⚠️ to ✅.
- **Staff routes authenticated (was gap 3).** PR #4's four staff routes are now
  mounted *and* guarded by `require_staff()`; the `require_staff_roles()` stub
  that returned a hardcoded dict is gone. The exposure has moved to the two
  customer routers instead (now gap 1 above).
- **Coverage floor raised (was a smaller item).** `pyproject.toml` sets
  `fail_under = 80` (was 0 — a floor that cannot fail). The unit suite measures
  **85.4%** on `main` at `2876fa2`, clearing it. The `test-integration` job passes
  `--cov-fail-under=0` explicitly, because with a global floor an empty
  `tests/integration/` would exit 1 (0% coverage) instead of 5 (no tests
  collected) and fail every pull request. Treat 80 as a ratchet: raise it as the
  suite comfortably clears higher numbers, never lower it.

---

## How to re-verify this document

Every claim above is checkable with commands that touch nothing:

```bash
# A03 - no interpolated SQL
git grep -nE "execute\((f\"|f')" -- src

# A07 - rate limiting wired?
git grep -nE "slowapi|Limiter" -- src

# A01 - which routers carry an auth dependency? (gap 1)
git grep -nE "require_staff|require_roles|get_current_token" -- src/presentation/api/routers
# cross-check against the mounted table: every path must have a security block
python -c "import json; d=json.load(open('docs/api/openapi.json')); \
print([p for p,v in d['paths'].items() for m in v.values() if 'security' not in m] or 'all guarded')"
# Expected output while gap 1 is open:
#   ['/', '/api/v1/health', '/api/v1/reservations',
#    '/api/v1/reservations/{reservation_id}/cancel', '/api/v1/reviews/']
# '/' and '/api/v1/health' are intentionally public (service index, liveness
# probe). The other three are the gap: they write business data unauthenticated.

# A09 - does anything actually write an audit row? (gap 2)
# Expect ONLY the definition in src/common/audit.py plus comments, until wiring lands
git grep -n "record_audit" -- src

# A08/A09 - migration chain is complete and reversible
pytest tests/unit/test_migration_completeness.py -v

# A02/A06 - all quality gates
ruff check src tests && ruff format --check src tests && mypy src
black --check src tests
bandit -r src -c pyproject.toml --severity-level medium
pytest tests/unit -m "not integration and not concurrency and not slow" --cov=src

# A08 - the archived API document matches the running app (diff should be empty;
# regenerate on Linux/CI, a Windows regeneration differs by line endings only)
python scripts/export_openapi.py --output /tmp/openapi-check.json
diff /tmp/openapi-check.json docs/api/openapi.json

# A09 - the table really gets created by migrations
alembic -x url=sqlite:////tmp/probe.db upgrade head
```

If a row says ✅ and its command fails, **the row is wrong** — fix the row or
fix the code, and say which. A hardening document that cannot be re-checked is
just an opinion.
