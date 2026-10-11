# System Architecture

**JC2001 BMIS Group 4 — Restaurant Reservation and Food-Ordering System**

> Status: living document. Update it when the architecture changes, not after.
> Owner: YAN ZHANG (engineering quality, README §6).

---

## 1. Why a three-tier architecture

Objective (f) commits the project to a three-tier architecture. This is not
ceremony — it buys three concrete things this project needs:

1. **The concurrency guarantee has one home.** All transaction and locking
   logic lives in the data tier (`src/data/`). The booking critical section is
   written once, in one place, and every caller gets the same guarantee. If
   booking logic were scattered across UI handlers, Objective (d) could not be
   tested or trusted.
2. **Ten people can work in parallel.** Each module owns a vertical slice of the
   application tier and cannot break another module's UI or persistence code.
   Merge conflicts drop to the shared boundaries listed in §6.
3. **REST API becomes a natural seam.** The presentation tier exposes HTTP; the
   application tier is pure Python. That means unit tests can call services
   directly with no HTTP overhead, and the Vue frontend can be replaced or
   tested independently.

---

## 2. Tier overview

```
┌──────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                          │
│  Vue 3 + Vite + TypeScript                                        │
│  ├─ src/presentation/web      customer app (book, order, review)  │
│  ├─ src/presentation/staff    waiter back office                  │
│  └─ src/presentation/manager  analytics dashboard + ECharts       │
└───────────────────────────────┬──────────────────────────────────┘
                                │  HTTP / JSON  (JWT bearer token)
                                │  OpenAPI contract in docs/api/
┌───────────────────────────────▼──────────────────────────────────┐
│  TIER 1 — PRESENTATION                            src/presentation│
│  FastAPI routers · request/response models · auth dependencies    │
│  Knows about HTTP. Knows nothing about business rules.            │
│  ├─ api/main.py       app factory, health, middleware wiring     │
│  ├─ api/routers/      one router per module                      │
│  └─ web|staff|manager Vue SPAs (static build served separately)   │
├──────────────────────────────────────────────────────────────────┤
│  TIER 2 — APPLICATION                               src/application│
│  Services, domain rules, state machines, transactions.            │
│  Knows nothing about HTTP, nothing about SQL dialects.            │
│  ├─ reservation/  booking flow, seat holds, state machine         │
│  ├─ ordering/     menu browsing, order submission                 │
│  ├─ membership/   RBAC, points ledger, tiers, coupons             │
│  ├─ review/       order-verified reviews, Bayesian ranking        │
│  └─ analytics/    dashboard aggregates, hybrid recommender        │
├──────────────────────────────────────────────────────────────────┤
│  TIER 3 — DATA                                          src/data  │
│  SQLAlchemy 2.0 models · repositories · migrations · engine       │
│  The only tier that may contain SQL.                              │
│  ├─ database.py     engine, session, locking helpers              │
│  ├─ schema/         ORM models (one module per file)              │
│  ├─ repository/     query and persistence per aggregate           │
│  └─ migration/      Alembic env.py + versions/                    │
└───────────────────────────────┬──────────────────────────────────┘
                                │  MySQL 8.0 (InnoDB, utf8mb4)
┌───────────────────────────────▼──────────────────────────────────┐
│  MySQL 8.0.12 — transactions · row locks · unique constraints     │
└──────────────────────────────────────────────────────────────────┘

  CROSS-CUTTING (src/common/) — used by all three tiers:
  config.py · security.py (JWT, RBAC, bcrypt) · audit.py · middleware.py
```

---

## 3. Dependency rule

**Dependencies point downward, never upward or sideways across modules.**

| Tier | May import | Must NOT import |
|------|-----------|-----------------|
| Presentation | application, common, data (for `Depends(get_db)`) | — |
| Application | data, common | `fastapi`, `src.presentation.*`, another module's internals |
| Data | common | application, presentation |
| Common | (nothing in `src/`) | everything else |

Two consequences worth stating explicitly:

* **`fastapi` must not appear in `src/application/`.** The moment a service
  function takes a `Request` or raises `HTTPException`, it becomes untestable
  without an HTTP layer and locked to one framework. Services raise domain
  exceptions; routers translate them into HTTP status codes.
* **One module must not import another module's internals.** `review` needs to
  know whether a customer ordered a dish (Objective c: "only customers who
  actually ordered a dish can review it"), but it must ask through a published
  service interface, not by reaching into `ordering`'s repository. Otherwise
  the two modules cannot be developed or tested independently.

---

## 4. Request lifecycle

A staff member changing a reservation status:

```
1. Vue staff app  → PATCH /api/v1/reservations/42/status
                    Authorization: Bearer <JWT>

2. middleware.py  RequestContextMiddleware assigns an X-Request-ID,
                  starts the timer, and will add security headers on the way out.

3. api/routers/   The route declares its guard:
                    dependencies=[Depends(require_roles(Role.WAITER, Role.MANAGER))]
                  security.py verifies the JWT signature and expiry, then checks
                  the role claim. Wrong role → 403. Bad token → 401.

4. api/routers/   Pydantic validates the request body. Invalid → 422 with a
                  field-level error list.

5. api/routers/   Calls the application service, passing the session from
                  Depends(get_db) and the authenticated identity.

6. application/   reservation.change_status(session, id, new_status, actor)
                  · loads the row with SELECT ... FOR UPDATE (lock_for_update)
                  · validates the transition against the state machine
                  · updates fields
                  · calls record_audit(...) inside the SAME session

7. session.commit()  Reservation change and audit row commit together, or both
                     roll back. No audit record for a change that never happened.

8. api/routers/   Serialises the ORM object into a response model.
                  Never return an ORM object directly — it leaks columns that
                  are not part of the API contract.

9. middleware.py  Logs "PATCH /api/v1/reservations/42/status -> 200 in 14.2ms"
                  with the request id, adds the security headers, returns.
```

On any exception at step 6 or 7, `get_db` rolls back and the error handlers in
`middleware.py` produce the standard envelope
`{"error": {"code", "message", "request_id"}}` without leaking internals.

---

## 5. The booking critical section

This is the technical core of the project (Objective d) and the part most likely
to be examined closely. Three mechanisms, all required:

### 5.1 Pessimistic lock — serialise the contenders

```python
existing = lock_for_update(session, Reservation,
                           Reservation.table_id == table_id,
                           Reservation.slot_start == slot_start)
```

`SELECT ... FOR UPDATE` takes an InnoDB exclusive row lock held until commit. A
second concurrent transaction attempting the same select **blocks** rather than
reading stale data. Without this, both requests read "no reservation exists" and
both proceed to insert.

**Keep the locked region short.** No HTTP calls, no slow computation between
locking and committing — a long-held lock under load produces lock-wait timeouts
(MySQL default 50 s) and deadlocks.

### 5.2 Optimistic lock — detect lost updates

SQLAlchemy's `version_id_col` increments a version column on every UPDATE and
includes the expected version in the WHERE clause. If another transaction
committed first, zero rows match and SQLAlchemy raises `StaleDataError` instead
of silently overwriting. This covers updates to an existing reservation, which
`FOR UPDATE` alone does not fully protect against at higher isolation subtleties.

### 5.3 Unique constraint — the database has the final say

```sql
UNIQUE KEY uq_reservations_table_slot (table_id, slot_date, slot_start)
```

This is the mechanism that makes the guarantee **real** rather than hopeful. If
both application-level checks ever fail — a bug, a race in code nobody
anticipated, a hand-written query that forgot the lock — MySQL itself rejects
the duplicate row. The application catches `IntegrityError` and converts it into
"this slot was just taken".

> **Why all three?** A unique constraint alone gives correctness but poor UX:
> every conflict becomes an exception. Locking alone gives good UX but is
> defeated by any code path that forgets the lock. Together: the lock handles
> the normal case gracefully, the constraint guarantees the invariant holds no
> matter what any code path does.

### 5.4 What the concurrency test must prove

`tests/concurrency/` needs to demonstrate that with N simultaneous booking
requests for the same table and slot, **exactly one** succeeds and N−1 receive a
conflict response. Requirements:

* Real MySQL, not SQLite — SQLite's locking model does not reproduce InnoDB's
  behaviour, so the test would pass while the guarantee was absent.
* Genuine parallelism (`ThreadPoolExecutor` with N workers, or separate
  processes). Sequential requests in a loop prove nothing.
* Assert on the **database state** afterwards (`SELECT COUNT(*) == 1`), not only
  on HTTP responses. The invariant that matters is the row count.
* Run it repeatedly in CI. A race that passes once and fails once in twenty runs
  is still a failure; a single green run is not evidence.

This test is the single most important artefact in the repository for Objective
(d). It is due 30 Nov 2026 and assigned to GEMAN MENG and JIAYI TAN.

### 5.5 Temporary seat holds

Objective (a) requires holds with automatic expiry. Design:

* A hold row carries `expires_at = created_at + settings.seat_hold_ttl_seconds`
  (default 600 s, configurable without a code change).
* Availability queries treat a hold as occupying the slot only while
  `expires_at > NOW()`.
* Expiry needs **no background job** to be correct: an expired hold simply stops
  counting. A periodic cleanup job is still worthwhile to keep the table small,
  but correctness must not depend on it running — if the job dies, bookings must
  still work.

This avoids the classic failure mode: a job-based design where a crashed job
leaves tables locked forever.

---

## 6. Shared boundaries

These are the places ten people collide. Each has a named owner (README §6) and
a rule. Changing one requires announcing it in the group chat **before** opening
the PR, because someone else's code already depends on it.

| Boundary | Location | Owner | Rule |
|----------|----------|-------|------|
| Database schema | `src/data/schema/`, `src/data/migration/versions/` | YUANYUAN XUE | Never edit an applied migration; add a new one. Coordinate new tables/columns in chat first. |
| REST API contract | `docs/api/`, `src/presentation/api/routers/` | YAN ZHANG | Agree the endpoint shape in `docs/api/` before writing client code. Breaking changes need a heads-up to all three frontend owners. |
| Alembic `env.py` model imports | `src/data/migration/env.py` | YUANYUAN XUE | A model not imported there is invisible to autogenerate, which will then try to **drop its table**. Add your model module to `_IMPORT_MODEL_MODULES`. |
| Reservation state machine | `src/application/reservation/` | KEYING CHEN | Staff backend and analytics both read reservation status. Any new state or transition must be announced. |
| Role definitions | `src/common/security.py` | YAN ZHANG | Four roles only. Adding one changes every guard in the system. |
| Error envelope | `src/common/middleware.py` | YAN ZHANG | The Vue frontend has one error-handling path built on this shape. |
| CI workflow | `.github/workflows/ci.yml` | YAN ZHANG | A red pipeline blocks all ten contributors. |

---

## 7. Module boundaries and interfaces

Each module publishes a service interface. Cross-module needs go through it.

| Module | Consumes from | Publishes |
|--------|--------------|-----------|
| `reservation` | `data` (tables, slots) | availability queries, booking, cancellation, state transitions |
| `ordering` | `data` (menu), `reservation` (is there an active booking?) | menu browsing, order submission, order lookup |
| `membership` | `data` | auth, roles, points balance, tier, coupon eligibility |
| `review` | `ordering` (**did this customer actually order this dish?**), `membership` | submit review, moderation actions, Bayesian-ranked dish list |
| `analytics` | `reservation`, `ordering` (read-only aggregates) | dashboard metrics, recommendations |

`review → ordering` is the interesting one: Objective (c) requires that only
customers who actually ordered a dish can review it. `review` must call an
`ordering` service method such as `has_ordered_dish(customer_id, dish_id)`,
**not** query the orders table directly. That keeps the definition of "actually
ordered" in one place — if the rule later changes to "ordered and completed",
only `ordering` changes.

`analytics` should read through **read-only** queries and never write to another
module's tables. Dashboard aggregation queries can be expensive; keep them out of
the booking critical section's tables where possible, and index for the
aggregation patterns the dashboard actually uses.

---

## 8. Data model sketch

Detailed DDL belongs in `src/data/schema/` and in Alembic migrations. The
entities implied by the proposal:

```
users(id, email, password_hash, role, tier_id, points_balance, created_at)
       role ∈ {customer, waiter, manager, admin}
       password_hash is bcrypt — never plaintext (see common/security.py)

membership_tiers(id, name, min_points, discount_rate)
points_ledger(id, user_id, delta, reason, expires_at, created_at)
       Append-only. Balance is derived, never edited in place, so every point
       can be traced to the order that earned it. Expiry is a query condition,
       not a background mutation.

coupons(id, code, type, value, min_spend, stackable, valid_from, valid_until)
user_coupons(id, user_id, coupon_id, status, redeemed_at)

dining_tables(id, label, seats, zone)
time_slots(id, starts_at, ends_at)      -- or a derived slot grid

reservations(id, user_id, table_id, slot_date, slot_start, party_size,
             status, version, created_at, updated_at)
       status ∈ {held, confirmed, seated, completed, cancelled, no_show}
       UNIQUE (table_id, slot_date, slot_start)   ← §5.3 safety net
       version is SQLAlchemy's version_id_col     ← §5.2 optimistic lock
       holds expire via expires_at, not a job     ← §5.5

menu_categories(id, name, display_order)
dishes(id, category_id, name, description, price, available, image_url)

orders(id, reservation_id, user_id, status, subtotal, discount_total,
       total, created_at)
order_items(id, order_id, dish_id, quantity, unit_price)
       unit_price is copied from the dish at order time. A later menu price
       change must not rewrite what a customer already paid.

reviews(id, dish_id, user_id, order_id, rating, body, status, created_at)
       order_id is NOT NULL and must reference an order containing that dish
       ← this is how "order-verified" (Objective c) is enforced structurally
       UNIQUE (dish_id, user_id, order_id) prevents review bombing
       status ∈ {pending, approved, rejected} for the moderation queue

audit_logs(...)  -- see src/common/audit.py, already implemented
```

**Note on the Bayesian average (Objective c).** Dish ranking uses a Bayesian
average rather than a plain mean, so a dish with one 5-star review does not
outrank a dish with two hundred 4.8-star reviews:

```
bayesian_rating = (v / (v + m)) * R  +  (m / (v + m)) * C

R = the dish's own mean rating
v = the dish's review count
C = the global mean rating across all dishes
m = a confidence threshold — the number of reviews at which a dish's own
    average starts to dominate. Tune m against real data; 10–25 is a
    reasonable starting range.
```

`C` and `m` must be **derived from the data and documented**, not hardcoded
magic numbers. Recompute `C` periodically; a stale global mean silently skews
every ranking.

---

## 9. Reservation state machine

Owned by KEYING CHEN. Transitions must be validated in the service layer — the
database stores the current state, it cannot enforce which transitions are legal.

```
                    ┌─────────────┐
      create hold   │             │  hold expires (§5.5)
   ─────────────────▶    held     ├──────────────────┐
                    │             │                  │
                    └──────┬──────┘                  ▼
                           │ confirm            (row deleted or
                           ▼                     marked expired)
                    ┌─────────────┐
                    │  confirmed  │
                    └──┬───────┬──┘
        guest arrives  │       │  customer or staff cancels
                       ▼       ▼
              ┌──────────┐  ┌───────────┐
              │  seated  │  │ cancelled │
              └────┬─────┘  └───────────┘
       meal ends   │
                   ▼
              ┌───────────┐
              │ completed │───▶ enables reviews (Objective c)
              └───────────┘

      no-show:  confirmed ──▶ no_show   (feeds the analytics no-show rate)
```

Rules:

* Transitions not drawn above are **rejected** by the service. `completed →
  seated` must not be possible, whatever the HTTP request says.
* Every transition writes an audit row (staff-initiated ones record the actor).
* Only `completed` reservations enable dish reviews — this is the structural
  basis for "only customers who actually ordered".
* `no_show` is a distinct terminal state, not a flavour of `cancelled`, because
  the analytics dashboard reports a no-show rate (Objective e).

---

## 10. Security architecture (OWASP Top 10)

Objective (f) requires OWASP Top 10 hardening. Mapping the controls that exist
in code today:

| OWASP | Control | Where |
|-------|---------|-------|
| **A01** Broken Access Control | Role guards on every back-office route; 403 for wrong role, 401 for bad token; guards refuse an empty role list | `common/security.py` |
| **A02** Cryptographic Failures | bcrypt password hashing; 72-byte limit enforced rather than silently truncated; JWT signed HS256 with a required 32+ char secret | `common/security.py` |
| **A03** Injection | SQLAlchemy ORM with bound parameters throughout — no string-concatenated SQL anywhere. **Reviewers must reject any raw SQL string built by concatenation.** | `data/` |
| **A04** Insecure Design | Reservation state machine validates transitions in the service layer; three-layer booking defence (§5) | `application/reservation/` |
| **A05** Security Misconfiguration | Production refuses to boot with a placeholder secret, weak DB password or wildcard CORS; `/docs` and `/openapi.json` disabled in production; hardened headers (nosniff, DENY framing, strict referrer, CSP + HSTS in production); non-root container user | `common/config.py`, `common/middleware.py`, `deploy/docker/` |
| **A06** Vulnerable Components | `pip-audit --strict` on every PR; dependencies version-bounded in `requirements.txt` | `.github/workflows/ci.yml` |
| **A07** Identification & Authentication Failures | Short-lived JWTs (60 min default, bounded 1–1440); unique `jti` per token for revocation; `alg: none` rejected; verification errors all map to one opaque 401 so an attacker cannot distinguish expired from forged | `common/security.py` |
| **A08** Software & Data Integrity Failures | Pinned dependency ranges; Alembic migrations as the only schema-change path | `requirements*.txt`, `data/migration/` |
| **A09** Security Logging & Alerting Failures | Audit table for every back-office mutation; correlation id across response header, app log and audit row; credential-like keys redacted before storage | `common/audit.py`, `common/middleware.py` |
| **A10** SSRF | No outbound URL fetching exists in this system — payment, SMS and third-party APIs are explicitly out of scope. **Do not add one without revisiting this row.** | n/a |

Remaining work, by module owner:

* **Input validation on every endpoint** — Pydantic models with explicit bounds
  (a `party_size` of −5 or 10 000 must be rejected at the edge).
* **Rate limiting** — `slowapi` is a declared dependency; wire the limiter into
  the app and apply `APP_RATE_LIMIT_REVIEW` to review submission (Objective c).
* **Authorisation on object access** — a waiter must not read another restaurant's
  data; a customer must not read another customer's reservation by guessing an id.
  Role guards alone do not cover this (**IDOR**, the most commonly missed item in
  student projects).
* **Audit logging in the staff and membership modules** — `record_audit` exists;
  every status-changing endpoint must call it.

---

## 11. Deployment topology

```
                    ┌──────────────┐
   browser  ───────▶│  Vue 3 SPA   │  static build (npm run build → dist/)
                    └──────┬───────┘  served by any static host or nginx
                           │  /api/v1/*  (JSON, JWT)
                    ┌──────▼───────┐
                    │  FastAPI     │  uvicorn, non-root user, port 8000
                    │  (Docker)    │  /health for the orchestrator
                    └──────┬───────┘
                           │  SQLAlchemy pool (size 10 + overflow 20)
                    ┌──────▼───────┐
                    │  MySQL 8.0   │  InnoDB · utf8mb4 · REPEATABLE READ
                    │  (Docker)    │  named volume for persistence
                    └──────────────┘
```

* **Frontend and API are deployed separately.** The SPA is static files; it talks
  to the API over HTTP. This is why JWT (stateless) was chosen over sessions —
  there is no shared server-side session store between the two.
* **CORS must list the SPA's real origin.** A wildcard with credentials is
  refused at startup in production (`common/middleware.py`).
* **`docker-compose.yml` maps host 3307 → container 3306** so the stack does not
  clash with a MySQL already running on a developer's machine.
* **Secrets come from the environment**, never from the image. The production
  image defaults to `APP_ENVIRONMENT=production` and will refuse to start with a
  placeholder secret — deploy through your platform's secret store.

---

## 12. Decisions and their consequences

Recorded so a reviewer can see the reasoning, and so the team does not relitigate
them in week eight.

| Decision | Why | What it costs |
|----------|-----|---------------|
| MySQL over PostgreSQL | The proposal allows either. MySQL 8's InnoDB gives complete transaction isolation, row locks and unique constraints — everything Objective (d) needs. The team's familiarity decided it. | PostgreSQL's richer constraint types (exclusion constraints) would express "no overlapping time ranges" directly; we express it with a discrete slot grid plus a unique constraint instead. |
| Discrete slots, not free-form time ranges | A unique constraint on `(table_id, slot_date, slot_start)` is simple, indexable and provably correct. Range-overlap checks are not enforceable by a unique constraint in MySQL. | Bookings snap to a grid. Slot length must be chosen up front and cannot vary per reservation without complicating the constraint. |
| JWT over server sessions | Frontend and API deploy separately; a stateless token needs no shared session store. | Revocation before expiry needs an explicit mechanism. We mint a unique `jti` per token so a deny-list is possible; **it is not implemented yet**. |
| FastAPI over Flask/Django | Auto-generated OpenAPI directly satisfies "documented REST API"; Pydantic validation; async support suits the concurrency test. | The team must learn dependency injection and Pydantic. Async correctness is a new failure mode. |
| SQLAlchemy 2.0 over raw SQL | Native `version_id_col` optimistic locking; the ORM makes bound parameters the default, which is the A03 injection control. | An abstraction layer to learn; `StaleDataError` must be caught and translated deliberately. |
| Alembic for all schema changes | Reproducible schema; a fresh environment reaches the same state as production. | Discipline required — the fastest way to break it is someone editing the database by hand. |
| Vue 3 + Element Plus | Composition API is approachable; Element Plus supplies tables and forms, which is most of the staff backend and the manager dashboard. | Not the smallest bundle. Irrelevant for a course prototype. |
| ECharts for the dashboard | Objective (e) needs a heat map, line and bar chart; ECharts covers all three in one dependency. | A large library for a handful of charts. |
| Audit rows written in the business transaction | An audit trail that records a change which never happened is worse than none. | Audit writes cannot be deferred to a queue; a slow audit insert slows the request. Acceptable at this scale. |
| No payment, no SMS | Explicitly out of scope in the proposal. | Also removes the SSRF surface (A10) — do not add outbound HTTP without revisiting §10. |

---

## 13. Open questions to resolve before implementation

Assign each to an owner in the group chat; they block real coding.

1. **Slot granularity** — 30 min, 60 min, or 90 min? Determines the unique
   constraint and the whole availability UI. *(Owner: KEYING CHEN + YUANYUAN XUE)*
2. **How long may a party keep a table?** A 2-hour seating cap affects turnover
   analytics. *(Owner: KEYING CHEN)*
3. **Points earning rule** — per yuan spent, or per order? Expiry window?
   *(Owner: RONG CONG + GEMAN MENG)*
4. **Coupon stacking** — the proposal says "clearly defined discount-stacking
   rules". Define them: which combinations are legal, and in what order are
   discounts applied? Order changes the total. *(Owner: RONG CONG + GEMAN MENG)*
5. **Bayesian `m`** — what review count counts as "established"? Needs a
   decision before the ranking can be evaluated. *(Owner: RUNYI PENG)*
6. **Recommender inputs** — collaborative filtering on order history, content-based
   on dish categories, or both? "Hybrid" needs a concrete definition to be
   evaluated with Precision@K and MAE. *(Owner: HUANPAI LI + RUNYI PENG)*
7. **Moderation policy** — auto-publish then review, or hold until approved?
   Affects the review module's state machine. *(Owner: RUNYI PENG)*
8. **No-show definition** — a confirmed reservation not seated within how many
   minutes? The analytics rate depends on it. *(Owner: HUANPAI LI)*
