# Restaurant Reservation and Food-Ordering System

**JC2001 Group Project — BSc (BMIS), Group 4**

A proof-of-concept prototype that moves restaurant reservations and food ordering online, guarantees
concurrency-correct seat booking, and turns booking / order data into management insight.

---

## 1. Why this project

Many small and medium-sized restaurants still take bookings by phone and record them on paper, and
staff write orders by hand from printed menus. This causes booking conflicts, lost reservation
records and order-entry errors. Customers cannot see dish information or real-time seat
availability, and staff cannot easily collect booking and order statistics.

Naive digital tools add two further problems:

1. When reservation data lives in local files, the system cannot guarantee **atomic booking**, so two
   customers may take the same table for the same time slot at once.
2. Restaurants have no reliable way to collect **trustworthy dish feedback** backed by real orders,
   or to turn booking and order data into management decisions.

We therefore build a low-cost digital system that keeps reservations and orders online, guarantees
correct concurrent booking, and supports data-driven restaurant operations.

---

## 2. Scope

### In scope — five integrated modules

| # | Module | What it does |
|---|--------|--------------|
| 1 | **Reservation** | Seat reservation with concurrency-correct booking: relational DB with transactions, optimistic locking and a unique-constraint safety net; temporary seat holds with automatic expiry; explicit reservation state machine. An automated concurrency test verifies that only one of many simultaneous bookings succeeds. |
| 2 | **Ordering** | Customer side: menu browsing with category display and food-order submission. Staff backend: view reservation lists, update reservation status, access customer food orders. |
| 3 | **Membership & Loyalty** | Registration / login with role-based access control (customer, waiter, manager, admin); points ledger with expiry rules; membership tiers; coupons with clearly defined discount-stacking rules. |
| 4 | **Ratings & Reviews** | Only customers who actually ordered a dish can review it; dishes ranked by **Bayesian average** rather than a simple mean; rate limiting; staff moderation queue. |
| 5 | **Analytics** | Manager dashboard with revenue trends, table turnover, an hourly demand heat map and no-show rate; plus a lightweight hybrid recommender evaluated offline with Precision@K and MAE. |

### Out of scope — explicitly NOT implemented

- Online payment
- SMS notification
- Any commercial cloud database, payment or messaging API integration

Data is stored in a **self-hosted relational database (MySQL / PostgreSQL)** to guarantee
transactional consistency.

---

## 3. Engineering quality commitments

| Commitment | Status | Where |
|---|---|---|
| Three-tier architecture with a **documented REST API** | ✅ framework in place | `docs/design/ARCHITECTURE.md`, `docs/api/openapi.json` |
| Unit / integration / concurrency tests with **coverage reports** | 🟡 unit 184 passing (80.5% coverage); integration & concurrency pending | `tests/` |
| **CI running on every pull request** | ✅ live | `.github/workflows/ci.yml` |
| **OWASP Top 10** hardening | 🟡 framework-level controls done; per-endpoint validation pending | `src/common/`, `ARCHITECTURE.md` §10 |
| **Audit logs** for back-office changes | ✅ implemented, not yet wired to module endpoints | `src/common/audit.py` |
| **Docker** deployment | ✅ configured, not yet smoke-tested | `deploy/docker/` |
| A **user manual** covering all modules | ⬜ not started (due 04 Dec) | `docs/user-manual/` |

### Technology stack

Decided in `技术选型.docx`; do not change it without a group decision, because
CI, the Dockerfile and every module's imports depend on it.

| Layer | Choice |
|---|---|
| Language | **Python 3.11** |
| Web framework | **FastAPI** + Uvicorn (auto-generated OpenAPI = the documented REST API) |
| Validation | **Pydantic v2** + pydantic-settings |
| ORM | **SQLAlchemy 2.0** (declarative, `version_id_col` for optimistic locking) |
| Migrations | **Alembic** |
| Database | **MySQL 8.0** (InnoDB, utf8mb4, READ COMMITTED) via PyMySQL |
| Auth | **PyJWT** (HS256) + **bcrypt** via passlib |
| Rate limiting | **slowapi** |
| Logging | **structlog** |
| Frontend | **Vue 3** + Vite + TypeScript, Pinia, Element Plus, ECharts |
| Testing | **pytest** + pytest-asyncio + pytest-cov |
| Lint / format / types | **Ruff**, **Black**, **mypy** |
| Security scan | **bandit**, **pip-audit** |
| CI / deploy | **GitHub Actions**, **Docker** + docker-compose |

> ⚠️ **Known dependency traps** (already fixed here; do not reintroduce):
> - Do **not** install `types-PyJWT` or `types-cryptography`. PyJWT ≥ 2.4 and
>   cryptography both ship `py.typed` with correct inline annotations; the old
>   stub packages shadow them with PyJWT-1.x-era signatures and make mypy report
>   a false `jwt.encode() -> bytes` error at every call site.
> - `pytest-asyncio` must be **1.x**, not 0.25.x. The older line calls the
>   deprecated `asyncio.get_event_loop_policy()`, and since this suite runs with
>   `filterwarnings = ["error"]`, that fails *every* test at setup on Python 3.12+.
> - `httpx2` is required, not optional: starlette ≥ 1.7 imports it first and only
>   falls back to `httpx` by emitting a `StarletteDeprecationWarning` — again an
>   error under this configuration.
> - `pydantic-settings` 2.15 no longer hard-depends on `python-dotenv`, but
>   `src/common/config.py` reads `.env`, so it stays pinned in `requirements.txt`.

---

## 4. Repository layout

```
.
├── docs/                      # All project documentation
│   ├── proposal/              # Proposal & Project Updates 1–4
│   ├── requirements/          # Requirements, use-case diagrams
│   ├── design/                # Three-tier architecture, DB schema, reservation state machine
│   ├── api/                   # REST API documentation
│   ├── testing/               # Test plans, concurrency test report, coverage reports
│   └── user-manual/           # User manual covering all modules
├── src/
│   ├── presentation/          # Tier 1 — UI & entry points
│   │   ├── web/               #   Customer-facing web app
│   │   ├── staff/             #   Restaurant staff backend UI
│   │   ├── manager/           #   Manager analytics dashboard
│   │   └── api/               #   REST API controllers / routes
│   ├── application/           # Tier 2 — Business logic, one folder per module
│   │   ├── reservation/
│   │   ├── ordering/
│   │   ├── membership/
│   │   ├── review/
│   │   └── analytics/
│   └── data/                  # Tier 3 — Persistence
│       ├── schema/            #   DDL, tables, constraints, indexes
│       ├── migration/         #   Migrations & local-file data import
│       └── repository/        #   Repository / DAO layer
├── tests/
│   ├── unit/
│   ├── integration/
│   └── concurrency/           # Automated concurrent-booking test
├── deploy/
│   ├── docker/                # Dockerfile, docker-compose
│   └── ci/                    # CI scripts & coverage config
└── .github/workflows/         # CI pipeline (runs on every pull request)
```

**What is already implemented** (the shared foundation — build on it, don't reinvent it):

```
src/common/config.py        Settings from env vars; refuses to boot production
                            with a placeholder secret, weak DB password or
                            wildcard CORS. Secrets are excluded from model_dump().
src/common/security.py      bcrypt hashing, JWT sign/verify, Role enum, and the
                            require_roles() / require_staff() guards.
src/common/middleware.py    Request-id correlation, hardening headers, and the
                            frozen envelope (code/message/data/request_id/
                            timestamp) with 5-digit business error codes.
src/common/errors.py        The frozen error-code catalogue + ApiError, so
                            services can signal a business rule without
                            importing FastAPI.
src/common/envelope.py      success()/failure() builders and the pagination
                            shape required by the contract.
src/common/audit.py         AuditLog table + record_audit() with automatic
                            redaction of credential-like keys.
src/data/database.py        Engine/session, lock_for_update() (SELECT … FOR UPDATE)
                            and StaleDataError handling — the Objective (d) toolkit.
src/presentation/api/main.py  App factory, /health, /api/v1/auth/me, OpenAPI docs.
tests/unit/                 184 passing tests, 80.5% coverage of src/.
deploy/docker/              Multi-stage Dockerfile + docker-compose with MySQL 8.0.
```

**What is still a placeholder** — each is owned by a named person in §6:

| Path | Waiting for | Owner |
|---|---|---|
| `src/application/reservation/` | booking service, seat holds, state machine | KEYING CHEN |
| `src/application/ordering/` | menu browsing, order submission | ZIHAN ZHU |
| `src/application/membership/` | registration/login, points, tiers, coupons | RONG CONG, GEMAN MENG |
| `src/application/review/` | order-verified reviews, Bayesian ranking, moderation | RUNYI PENG |
| `src/application/analytics/` | dashboard aggregates, hybrid recommender | HUANPAI LI |
| `src/data/schema/` | the ORM models for every table | YUANYUAN XUE |
| `src/presentation/{web,staff,manager}/` | the three Vue SPAs | module owners |
| `tests/integration/`, `tests/concurrency/` | DB-backed tests; the concurrent-booking test | GEMAN MENG, JIAYI TAN |
| `docs/{requirements,testing,user-manual}/` | requirements, test report, user manual | per §6 |

`src/presentation/api/main.py` registers module routers by convention: create a
`router` object in `src/application/<module>/router.py` and it is mounted at
`/api/v1/<module>` automatically. Missing modules are skipped with a debug log,
so a half-finished module cannot break the app for everyone else.

Read **[docs/design/ARCHITECTURE.md](docs/design/ARCHITECTURE.md)** before writing
code. It documents the dependency rule (which tier may import what), the booking
critical section's three-layer defence, the reservation state machine, the data
model, the shared boundaries that cause merge conflicts, and 8 open questions
that still need a group decision.

---

## 5. Timeline

| Phase | Key activities | Deadline |
|-------|----------------|----------|
| **Requirement & Design** | Finalise requirements; use-case diagrams and three-tier architecture design; relational DB schema and reservation state machine; prepare Project Update 1 | 12 Oct 2026 |
| **Prototype Implementation** | Customer module + staff backend; transactional seat-booking conflict check, menu viewing, order handling; membership & loyalty, ratings/reviews, manager analytics dashboard; prepare Project Updates 2 & 3 | 23 Nov 2026 |
| **Testing & Debugging** | Functional, integration and concurrency testing; automated concurrent-booking test and coverage reports; fix booking-conflict and order-storage bugs; OWASP Top 10 security check; front-end/back-end integration; prepare Project Update 4 | 07 Dec 2026 |
| **Documentation** | Technical report draft; user manual and REST API documentation; references and appendix (group workload profile draft) | 10 Dec 2026 |
| **Final Preparation** | Docker packaging and deployment check; presentation slides and recorded video; full consistency check across proposal, report, PoC software and presentation; final submission readiness | 14 Dec 2026 |

---

## 6. Team & task allocation

| Member | Module / responsibility | Deadline |
|--------|-------------------------|----------|
| **YAN ZHANG** | Engineering quality: three-tier architecture with documented REST API, unit/integration tests with coverage, CI on every PR, OWASP Top 10 hardening, audit logs, Docker deployment. Also: proposal drafting / review / submission, progress tracking, final deliverable packaging | 03 Dec 2026 (quality) · 14 Dec 2026 (proposal & packaging) |
| **KEYING CHEN** | Seat-reservation module: booking flow, conflict check, temporary seat holds with automatic expiry, reservation state machine | 15 Nov 2026 |
| **RANXI HE** | Staff backend: reservation-list and food-order-list display, reservation-status modification, order handling | 23 Nov 2026 |
| **GEMAN MENG** | Membership & loyalty (with RONG CONG); functional + integration testing and end-to-end front-end/back-end integration (with JIAYI TAN); presentation slides (with HUANPAI LI) | 23 Nov 2026 · 30 Nov 2026 · 08 Dec 2026 |
| **ZIHAN ZHU** | Ordering module: menu browsing, category display, order submission | 15 Nov 2026 |
| **HUANPAI LI** | Manager dashboard (revenue trends, table turnover, hourly demand heat map, no-show rate) and hybrid recommender evaluated offline (with RUNYI PENG); presentation slides (with GEMAN MENG) | 03 Dec 2026 · 08 Dec 2026 |
| **JIAYI TAN** | Functional + integration testing and the automated concurrency test (with GEMAN MENG); user manual with installation and operation guidance for all modules; recorded presentation MP4 video | 30 Nov 2026 · 04 Dec 2026 · 13 Dec 2026 |
| **YUANYUAN XUE** | Relational database layer: schema, transactions, optimistic locking, unique-constraint safety net, data migration from local files | 23 Nov 2026 |
| **RUNYI PENG** | Ratings & reviews module: order-verified review submission, Bayesian-average dish ranking, rate limiting, staff moderation queue; manager dashboard & recommender (with HUANPAI LI) | 23 Nov 2026 · 03 Dec 2026 |
| **RONG CONG** | Membership & loyalty module: registration/login with role-based access control (customer/waiter/manager/admin), points ledger with expiry rules, membership tiers, coupons with discount-stacking rules (with GEMAN MENG) | 23 Nov 2026 |

---

## 7. How to contribute

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full workflow. In short:

1. Ask the repository owner to invite you as a collaborator, and accept the invitation.
2. Clone the repo and set up Git identity.
3. Create a feature branch from `main`, named `feature/<module>-<short-desc>`.
4. Commit with Conventional Commits messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
5. Push your branch and open a **Pull Request**. CI runs automatically.
6. Get at least one approving review, then merge with **Squash and merge**.

**Never push directly to `main`.** `main` must stay deployable at every commit.

---

## 8. Getting started

```bash
git clone git@github.com:Isss10/bmis-group4-restaurant-system.git
cd bmis-group4-restaurant-system
git checkout -b feature/your-module
```

Then set up the backend:

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# macOS / Linux:       source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env        # then generate your own secret — see the file
python -c "import secrets; print(secrets.token_urlsafe(48))"

pytest                      # 184 unit tests, no database needed
ruff check src tests && black --check src tests && mypy src
```

Unit tests need no database. Anything under `tests/integration/` and
`tests/concurrency/` skips itself unless `APP_DB_HOST` is set — point it at a
scratch database, never one with data you care about.

To run the whole stack (MySQL 8.0 + the API) in one command:

```bash
docker compose -f deploy/docker/docker-compose.yml up --build
```

> **Windows users whose `pip install` appears to hang:** direct access to
> `pypi.org` can be extremely slow on some networks. Use a mirror instead —
> `pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt`.

The REST API documentation deliverable is generated from the running app:

```bash
python scripts/export_openapi.py --output docs/api/openapi.json
```

Re-run that after any change to a route, and commit the result — the archived
`openapi.json` is what reviewers read when they cannot start the app.

Module-level setup details (per-module environment variables, seeding data) will
be added to [`docs/user-manual/`](docs/user-manual/) as the prototype takes shape.
