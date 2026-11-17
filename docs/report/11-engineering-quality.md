<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: M10, M4
  TARGET: 4 pages          DUE: 4 Dec 2026
  STATUS: draft v1 (16 Nov) — assembled from committed evidence; coverage figure to be pulled from CI at merge
  SOURCES: .github/workflows/ci.yml, docs/design/OWASP_TOP10_HARDENING.md, src/common/ (config,
           security, audit, middleware, envelope, errors), src/data/migration/versions/ (0001–0004),
           docs/api/openapi.json, pyproject.toml, deploy/docker/
  RULE: no source code. Describe the pipeline, the controls and the evidence.
-->

# 11. Engineering Quality

> Objective (f) treats engineering quality as a first-class deliverable, not a wrapper around
> the features. This chapter is where the group demonstrates the software was *engineered*. The
> evidence almost all exists in the repository already — the work is to assemble it and explain
> *why* each control is there, which is what earns the marks, rather than to invent anything.

## 11.1 REST API design conventions

The API follows one frozen contract, agreed in week one and enforced by tests rather than by
convention. Freezing it early is the single decision that made ten-person parallel delivery
possible: every module owner codes against the same envelope, the same error vocabulary and the
same base paths, so a client written against one module works against all of them.

- **One base path per module**, each owned by one person: `/api/v1/{reservations, orders, staff,
  membership, reviews, analytics}`. Resource names are plural nouns.
- **A single response envelope** on every call: `code / message / data / request_id / timestamp`.
- **Five-digit business codes** distinct from the HTTP status: `0` success; `1xxxx` validation;
  `2xxxx` business rules (`20001` slot conflict, `20003` illegal transition, `20004` stale data);
  `3xxxx` authorisation (`30001` unauthenticated, `30003` wrong role); `5xxxx` server error. The
  HTTP status describes the transport; `code` describes *which rule* was violated, and the
  frontend switches on `code`.
- **`X-Request-ID`** correlation across the response header, the application log and any audit row
  a request produced (FR-XX-02).
- **ISO 8601 UTC** timestamps; **bounded pagination** (`page_size ≤ 100`, `10002` above).

The router registry in `main.py` maps each module to an import path and its frozen prefix, and a
loader mounts whatever exists. A missing module is logged and skipped so it cannot take `/health`
down; a *malformed* one is logged loudly with a traceback. The mounted prefixes and the absence of
`ordering`/`analytics` are tabulated in ch.4 §4.7.3.

The trade-off is stated plainly because the rubric rewards justified decisions: the tolerant
loader let ten people merge in parallel, and it is also why a declared-but-missing router fails
silently at debug level (§11.7). A benefit and a price, both real.

## 11.2 Continuous integration

`.github/workflows/ci.yml` runs on every pull request. Each job and what it protects against:

| Job | What it does | Protects against |
|---|---|---|
| **Repo hygiene** | blocks `.env`/`.pem`/`secrets/`, scans tracked files for hardcoded credentials, fails on files > 5 MB, fails on empty source files, checks the Conventional Commits subject | secrets in history; empty stub files passing as "done"; huge binaries in Git |
| **Lint & types** | ruff lint + format check, mypy over `src/` | style drift; type errors; unimportable code |
| **Security scan** | `pip-audit --strict` and bandit at medium+ | known-vulnerable dependencies; common Python security defects (NFR-04) |
| **Unit tests** | pytest with a coverage floor of 80 % on `src/` | regressions; silent coverage collapse (NFR-02) |
| **Integration & concurrency** | a real **MySQL 8.0 service container**; runs the actual Alembic migration chain, checks model/migration drift, then the integration + concurrency tests | schema that does not match the models; migrations that do not run |
| **Frontend (Vue 3)** | builds and type-checks the client | a frontend that does not compile |
| **membership-ui** | the membership client's own workflow and unit tests | regressions in the auth client |
| **Docker build** | builds the image and smoke-tests `/health` | an image that builds but cannot start (NFR-06) |
| **Aggregate gate** | merges require every required job green; ruleset `protect-main` enforces `CI passed` | merging broken code (NFR-03) |

The workflow also uses a `concurrency` group with `cancel-in-progress`, so a superseded run is
cancelled when someone pushes again — meaningful CI-minute savings with ten people opening PRs.
Branch protection is enforced by a repository ruleset (`protect-main`, `enforcement=active`) whose
required check is `CI passed`, with **zero bypass actors** — including the repository owner, so
nobody can force-merge a red PR.

### 11.2.1 Two defects the pipeline was changed to catch

These are the strongest evidence in the report that the group ran a real engineering process,
because both are recorded in the workflow's own comments and both are *classes* of defect, not
typos:

1. **Model/migration drift.** Two separate "ORM model with no migration" defects reached `main`
   before the integration job was made to run the real migration chain against real MySQL and fail
   on drift. The defect class: a model that exists in code but not in the schema passes every unit
   test that builds tables with `create_all()`, and fails only against a migrated database. The
   fix also replaced a hand-maintained model-import list with automatic discovery
   (`model_discovery.py`), because the hand list had itself omitted a table — the same root cause
   twice.
2. **A whole-pipeline INTERNALERROR.** An unset pytest-asyncio fixture loop-scope option emitted a
   deprecation warning during `pytest_configure`; because `filterwarnings = ["error"]`, that
   warning became an error *inside the configure hook* and produced exit code 3, failing both test
   jobs before a single test ran. The fix set the loop scope explicitly at its source rather than
   widening the warning filter — suppressing the symptom would have hidden the next genuine
   deprecation too.

Both stories end the same way: a check was added so the *class* cannot recur. That is what
distinguishes engineering from debugging, and it is worth half a page.

## 11.3 Security hardening against the OWASP Top 10 (NFR-04)

The full control-by-control mapping lives here (ch.2 §2.3.1 only summarises and cross-references
— agreed with M10 to avoid printing the table twice). `docs/design/OWASP_TOP10_HARDENING.md` is
the maintained source; it was re-verified against `main` at `14df591` on 14 Nov. Net position:
**7 categories fully hardened (A01–A06, A08), 2 partial (A07, A09), 1 not applicable (A10)**.

| OWASP 2021 | Control | Where | Status |
|---|---|---|---|
| A01 Broken Access Control | role guards on every writing route; actor derived from the token, never a body id; empty role list refuses everybody | `common/security.py`, routers | ✅ |
| A02 Cryptographic Failures | bcrypt cost ≥ 12; 72-byte limit enforced; secrets excluded from repr and dumps; JWT algorithm pinned (HS256) | `common/security.py`, `common/config.py` | ✅ |
| A03 Injection | SQLAlchemy ORM with bound parameters throughout; no interpolated SQL in `src/` | `data/` | ✅ |
| A04 Insecure Design | frozen envelope + error contract; `/docs` disabled in production; state machine validates transitions | `common/`, `application/reservation/` | ✅ |
| A05 Security Misconfiguration | production refuses to boot with a weak/placeholder secret or wildcard CORS; hardened response headers; non-root container | `common/config.py`, `common/middleware.py`, `deploy/docker/` | ✅ |
| A06 Vulnerable Components | `pip-audit --strict` and bandit on every PR; version-bounded dependencies | `.github/workflows/ci.yml` | ✅ |
| A07 Identification & Auth Failures | short-lived JWTs (60 min, bounded 1–1440); `alg=none` rejected; login/register rate-limited 5/min | `common/security.py`, `routers/membership.py` | ⚠️ review submission still un-rate-limited (FR-REV-04) |
| A08 Software & Data Integrity | Alembic migrations only; real chain runs in CI against MySQL 8; auto-discovered completeness guard | `data/migration/`, CI | ✅ |
| A09 Security Logging & Alerting | append-only `audit_logs`; before/after snapshots; credential redaction; request-id correlation | `common/audit.py` | ⚠️ wired in membership only; reservation/order/review/points mutations still unwired (FR-XX-03) |
| A10 SSRF | no outbound URL fetching anywhere | n/a | ➖ not applicable (no payment/SMS/webhook) |

The two partial rows are tracked with owners and dates in ch.11 §11.7 and in the OWASP document's
"Open gaps" table. A10 is genuinely not applicable — there is no client-supplied URL fetch — and
the document records what would make it applicable again (adding any outbound HTTP), so the "n/a"
is defensible rather than dismissive.

## 11.4 Audit logging (FR-XX-03, NFR-05)

`src/common/audit.py` provides a *queryable* audit trail, not just log lines: log files rotate and
are lost, but a manager asking "who changed this reservation's status last Tuesday?" needs rows
that survive restarts. Design points worth explaining:

- **`record_audit()` appends inside the caller's transaction and does not commit.** That atomicity
  is the whole point — a trail recording a change that never happened is worse than none, and a
  change with no trail is what FR-XX-03 prevents.
- **Credential redaction is unconditional and recursive**: keys containing `password`, `token`,
  `secret`, `authorization`, `api_key`, `cvv`, `card_number`, `cookie` and similar are replaced
  with `[REDACTED]` before storage, while non-sensitive context (e.g. a `reason`) is preserved.
  Redaction happens on the *write* path because an audit log that stored a password in order to
  prove who changed it would have created a worse problem than the one it solves.
- **Role is snapshotted per row** rather than joined from `users`, so history stays correct after
  someone's role changes. `user_agent` is truncated; only changed fields are stored.
- Composite indexes cover the two real query shapes (who-did-what, who-touched-this-object).

🔧 **Status:** the infrastructure is built and unit-tested, but only the membership module calls
it today; reservation status, order status, review moderation, points and coupon mutations write no
audit row yet (§11.7).

## 11.5 Configuration and secrets management

Configuration is environment-only (`common/config.py`, every variable `APP_`-prefixed). The
production profile **refuses to start** if `APP_JWT_SECRET_KEY` is empty/placeholder/under 32
characters, if the DB password is weak, or if CORS contains `*`. Fail-fast is deliberate: a
misconfigured production instance that boots successfully is more dangerous than one that refuses
to start, because the warning would be ignored while the exposure would be live.

## 11.6 Containerisation and deployment (NFR-06)

A multi-stage Dockerfile builds wheels in a builder stage and ships only the runtime plus
installed packages in the final image (smaller surface, OWASP A05), runs as a non-root `appuser`,
and carries a `HEALTHCHECK` against `/health`. `docker-compose.yml` starts MySQL 8.0 (InnoDB,
`utf8mb4`, **READ COMMITTED** at the server level) beside the API; the API container runs
`alembic upgrade head` before serving, so a fresh volume cannot run against an un-migrated schema.
The CI `Docker build` job builds the image and smoke-tests it. Full start-up steps are in
`INSTALL.md`.

## 11.7 Known engineering limitations

Stated candidly because the rubric rewards honest evaluation and ch.13 builds on this. As of
`main` at `9258e0a` (16 Nov):

| Limitation | Why it matters | Owner |
|---|---|---|
| `/api/v1/orders` declared but not mounted; `/api/v1/analytics` mounted but returns hardcoded data | two contracted endpoint groups are absent or fake, and the tolerant loader hides it at debug level | M5 / M6 |
| The concurrency test is never collected by CI (no marker) and the behaviour it targets is unimplemented | **the Objective (d) evidence the pipeline was built to produce is not produced** (ch.12 §12.4) | M7 / M8 / M2 |
| Audit logging wired only in membership | FR-XX-03 unmet for every back-office change outside membership | M1 + module owners |
| Review submission not rate-limited | FR-REV-04 unmet; a spam/ranking-distortion vector | M9 |
| Loyalty module present only in a duplicate upload directory, not the running app; its migration collides at `0004` | points/tiers/coupons are not part of the deployed system | M4 |
| `AnalyticsDashboard.vue` committed but never imported/mounted; no staff or manager SPA | the manager surface is not user-reachable | M6 / M3 |
| Docker image never run end-to-end on a clean machine (no Docker on the maintainer's box) | reproducibility for the examiner is unverified | M1 |
| Committed `docs/api/openapi.json` is stale (routes added since the last export); no CI drift check | the documented surface and the running app can disagree | M1 |

The concrete fix for the first item is to make the loader fail — or emit a CI-visible warning —
once every contracted module is expected to exist; the workflow comment already says to remove the
tolerance when the modules land.

## 11.8 Test coverage

The unit suite collects **331 tests** at this baseline and CI enforces a coverage floor of
`fail_under = 80` on `src/`. ⚠️ **The exact achieved percentage must be pulled from the CI
coverage artifact at merge time, not estimated** — the artifact requires authenticated download,
so it is recorded here as a value to fill in on 4 Dec rather than a number to assert now. The floor
is treated as a ratchet: raised as the suite clears higher numbers, never lowered. The integration
job passes `--cov-fail-under=0` explicitly, because with a global floor an empty integration
directory would exit 1 (0 % coverage) rather than 5 (no tests collected) and fail every PR.

---

## Author's notes — to resolve before merging

- [ ] **Fill in the real coverage percentage** from the CI `coverage-unit` artifact (§11.8) on
      4 Dec. Do not write an estimate; the number is checkable and a wrong one is a visible defect.
- [ ] **§11.3 must not duplicate ch.2 §2.3.1.** M10 has the same instruction; one of you confirm
      with the other. The full table is here; ch.2 summarises.
- [ ] **§11.7 needs a full re-check on 4 Dec.** Most of these gaps are being worked on; move
      anything fixed into the body and delete the row. The chapter is only credible if §11.7
      matches `main` on the day it is merged.
- [ ] Regenerate `docs/api/openapi.json` from the running app before §11.1 is finalised (FR-XX-04),
      so the documented surface matches what is mounted; consider adding a drift check to the
      hygiene job.
- [ ] This chapter is mostly assembly — the workflow file, the OWASP document, the audit module,
      four migrations and the pyproject gates all exist. Budget the time for explaining *why*, not
      for describing *what*.
