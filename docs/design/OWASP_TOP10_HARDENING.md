# OWASP Top 10 (2021) Hardening Status

**Scope:** backend `src/` and deployment `deploy/`.
**Audience:** the group, and whoever assesses Objective (f).
**Last verified:** 2026-10-25, against branch `fix/audit-logs-migration`.

Every row below states **where the control lives** and **how it was verified**.
Nothing here is aspirational: the ✅ rows were confirmed by running the code or
reading the exact file, and the ❌ rows are known gaps with an owner and a date.

---

## Summary

| # | OWASP 2021 category | Status | Primary control |
|---|---|---|---|
| A01 | Broken Access Control | ⚠️ Partial | `require_roles()` dependency; not yet applied to any business route |
| A02 | Cryptographic Failures | ✅ Done | bcrypt cost 12; secrets excluded from repr and dumps; HSTS in production |
| A03 | Injection | ✅ Done | SQLAlchemy ORM throughout; no interpolated SQL in `src/` |
| A04 | Insecure Design | ⚠️ Partial | Envelope + frozen error contract on `feature/contract-alignment`, **not yet on main** |
| A05 | Security Misconfiguration | ✅ Done | Production boot refuses weak secrets and wildcard CORS; docs disabled in production |
| A06 | Vulnerable & Outdated Components | ✅ Done | `pip-audit --strict` and Bandit in CI on every pull request |
| A07 | Identification & Authentication Failures | ⚠️ Partial | JWT issued and verified; **no rate limiting on login** |
| A08 | Software & Data Integrity Failures | ✅ Done | Alembic migrations only; migration-completeness guard in the unit job |
| A09 | Security Logging & Alerting Failures | ✅ Done | `audit_logs` table + `record_audit()` with credential redaction |
| A10 | Server-Side Request Forgery | ➖ Not applicable | No outbound URL fetching anywhere in `src/` |

**Net position:** 5 fully hardened, 3 partial with named gaps, 1 not applicable.
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

`require_roles()` is defined and unit-tested, but **no business route uses it
yet**, because no business routes are merged. Verified on
`feature/staff-backend-api` (2026-10-25): `src/presentation/api/staff.py`
declares four routes — `/staff/orders`, `/staff/orders/{order_id}`,
`/staff/reservations`, `/staff/reservations/{reservation_id}` — with **no
authentication dependency on any of them**. Today they return 404, because that
router is not registered in `main.py` (the started app exposes only `/`,
`/api/v1/auth/me` and `/health`). The exposure is therefore latent, not live —
and it becomes live the moment someone wires the router in. Its four service
methods are also still `pass` stubs.

**Rule for every module owner:** a route that reads or writes business data must
declare `dependencies=[Depends(require_staff)]` or a narrower role gate. If you
are unsure which gate, use the stricter one — loosening later is one line, and a
missed gate is an incident.

**How to verify yours:** open `http://localhost:8000/openapi.json` after merging
and confirm your paths carry a `security` block. An authenticated API whose
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

**Remaining surface:** the frontend. `frontend/` is a static HTML prototype
today; when it is rebuilt as the Vue 3 SPA, avoid `v-html` with
user-supplied content — that reintroduces stored XSS regardless of how clean the
backend is.

---

## A04 — Insecure Design ⚠️

**What exists**

- A frozen response-envelope contract and a single error vocabulary live in
  `src/common/envelope.py` and `src/common/errors.py`.
- Exception text is deliberately **not** returned to clients: `middleware.py`
  documents that `str(exc)` is excluded, so a 500 says "Internal Server Error"
  and nothing more. Stack traces stay in the logs, correlated by `X-Request-ID`.
- Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are **disabled in
  production** — `docs_url="/docs" if not cfg.is_production else None`. An
  unauthenticated attacker should not get a machine-readable map of the API.
- `src/data/database.py` documents the isolation level and locking assumptions
  the concurrency design depends on, rather than leaving them implicit.

**The gap**

Both envelope files are on `feature/contract-alignment`, **which has no pull
request open and is not on main**. Until it merges, main has no shared error
contract, and each module invents its own response shape. This is the highest
leverage unmerged change in the repository.

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

Verified locally on 2026-10-25: `ruff check`, `ruff format --check`, `mypy` and
`bandit --severity-level medium` all pass.

> `black --check` is also a CI step. It could not be executed on this machine —
> the OS application-control policy blocks black's compiled extension
> (`DLL load failed ... 应用程序控制策略已阻止此文件`). `pyproject.toml` sets
> `line-length = 100` for **both** ruff and black, and ruff's formatter agrees
> with black on this configuration, so the ruff result is a reliable proxy. The
> CI black step remains authoritative.

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
attached to the application**, so no endpoint is actually limited. This is
credential-stuffing exposure on the login route.

This must be fixed on `feature/contract-alignment`, **not** on main directly:
that branch rewrites `src/presentation/api/main.py` (+128/−30) and
`src/common/middleware.py`, so wiring the limiter against main now would
guarantee a conflict.

**Why the limits are per-route rather than global:** a blanket `200/minute`
throttles an attacker no more than a legitimate customer. Login needs something
far tighter (a few attempts per minute per IP), and review submission needs the
`5/minute` limit that Objective (c) already specifies.

---

## A08 — Software & Data Integrity Failures ✅

- Schema changes go **only** through Alembic migrations
  (`src/data/migration/versions/`). `Base.metadata.create_all()` is used in
  tests, never in deployment.
- `deploy/docker/docker-compose.yml` runs `alembic upgrade head` at container
  start, so a deployed image cannot run against a schema it did not create.
- **New as of this commit:** `tests/unit/test_migration_completeness.py` runs the
  real migration chain against a scratch SQLite database and compares the result
  with `Base.metadata` in both directions — a model with no migration fails the
  unit job, and a stale migration that no model declares also fails. It also
  asserts a single migration head, that `src.common.audit` is registered for
  autogenerate, and that the chain survives up → down-to-base → up.
- The committed `docs/api/openapi.json` currently matches the generated document
  **byte for byte** — verified on 2026-10-25 by calling `create_app().openapi()`
  and comparing the JSON. There is **no CI check** for this, so the two can drift
  the moment someone adds a route without re-exporting. Re-export with
  `python scripts/export_openapi.py` after any route change, and consider adding
  a diff check to the `hygiene` job.
- The `hygiene` job blocks committed secrets and `.env` files, and scans tracked
  files for hardcoded credentials.
- The `hygiene` job validates pull-request titles and commit messages against
  the conventional commit format, and blocks large files that belong outside Git.

**Why the guard exists:** `audit_logs` shipped with a model and no migration.
Every `record_audit()` call raised `no such table: audit_logs` on a migrated
database — but the suite stayed green, because `conftest.py` builds its schema
with `create_all()` and no CI job ran a migration. The guard was
mutation-tested: deleting migration `0002` fails 4 tests; removing
`src.common.audit` from `_IMPORT_MODEL_MODULES` fails 3.

---

## A09 — Security Logging & Alerting Failures ✅

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

**Verified end-to-end on 2026-10-25:** `alembic upgrade head` creates the table
with all 14 columns and all 9 indexes; `record_audit()` writes and reads back
correctly; redaction confirmed; `downgrade` to base removes the table cleanly
and re-`upgrade` reproduces it identically.

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

Three items, each with an owner and a date. Ordered by how much they block.

| # | Gap | Blocks | Owner | Target |
|---|---|---|---|---|
| 1 | `feature/contract-alignment` has **no pull request open**. Envelope, error contract, rate-limit wiring point and the new router loader are all stranded on it. Nothing downstream can build on main until it lands. | A04, A07 | **Member1** | open the PR now |
| 2 | **Rate limiting not wired.** `slowapi` is installed and limits are configured, but no `Limiter` is attached to the app. Do this on the contract branch to avoid a guaranteed conflict in `main.py`. | A07 | **Member1** | with gap 1 |
| 3 | `feature/staff-backend-api` declares **four routes with no authentication dependency** and its four service methods are `pass` stubs. The routes are not registered in `main.py` today (they 404), so the exposure is latent — but it goes live the moment the router is wired in. | A01 | **M2 (YAN ZHOU)** | before merge |

Two smaller items that do not block a merge:

- **Coverage floor is 0.** `pyproject.toml` has `fail_under = 0` with a comment
  saying to raise it before final submission. Actual coverage is 86.7%. Set it
  to 80 so a regression cannot slip through unnoticed.
- **`tests/integration/` and `tests/concurrency/` are empty.** CI tolerates the
  resulting exit code 5 with an explicit comment, so the pipeline is not broken
  — but the concurrency test that proves lost-update prevention is an Objective
  (d) deliverable due 30 Nov, and it does not exist yet.

---

## How to re-verify this document

Every claim above is checkable with commands that touch nothing:

```bash
# A03 - no interpolated SQL
git grep -nE "execute\((f\"|f')" -- src

# A07 - rate limiting wired?
git grep -nE "slowapi|Limiter" -- src

# A08/A09 - migration chain is complete and reversible
pytest tests/unit/test_migration_completeness.py -v

# A02/A06 - all quality gates
ruff check src tests && ruff format --check src tests && mypy src
bandit -r src -c pyproject.toml --severity-level medium
pytest tests/unit -m "not integration and not concurrency and not slow" --cov=src

# A09 - the table really gets created by migrations
alembic -x url=sqlite:////tmp/probe.db upgrade head
```

If a row says ✅ and its command fails, **the row is wrong** — fix the row or
fix the code, and say which. A hardening document that cannot be re-checked is
just an opinion.
