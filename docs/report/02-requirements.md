<!--
  AUTHOR: M10 (RONG CONG)   SUPPORT: M1
  TARGET: 5–6 pages         DUE: 16 Nov 2026
  STATUS: draft v1 (23 Nov 2026)
  SOURCES: submitted proposal; docs/requirements/REQUIREMENTS.md §§4–7;
           docs/design/OWASP_TOP10_HARDENING.md; group handbook §§4–5
-->

# 2. Functional & Non-Functional Requirements

## 2.1 Requirements elicitation and method

The submitted group proposal set the problem and scope for a restaurant reservation
and food-ordering proof of concept. Its seven objectives (a)–(g), introduced in
Chapter 1, supplied the starting point for the team's requirements discussions.
The module owners translated the proposed workflows into observable requirements,
then used the internal collaboration handbook to agree on the interfaces shared by
their modules. For example, preventing double booking is a requirement from the
proposal. A 30-minute slot grid and a common error code give the database, booking
service, user interface and tests a precise way to implement and verify it.

The project is scoped to a single restaurant. Customers can reserve a table, order
from its menu and review dishes from completed orders. Waiters handle service.
Managers monitor operations and manage loyalty rules, while administrators manage
accounts. Online payments, SMS notifications and commercial cloud service
integrations are outside the submitted scope. The demo uses synthetic test data.

The requirements register uses stable identifiers of the form `FR-<MOD>-<nn>` for
functional requirements and `NFR-<nn>` for system qualities. The identifiers connect
the proposal to the use cases in Chapter 3, design in Chapters 4–5, implementation in
Chapters 6–11 and acceptance evidence in Chapter 12. The workload profile uses the
same identifiers to connect work to owners. **Must** denotes a core acceptance item
and **Should** a lower-priority commitment to test when implemented. A requirement's
priority describes its intended delivery, independently of the implementation and
test status. Table 2.9 records what the available artefacts can establish.

See the [submitted proposal](../proposal/JC2001-Group4-Project-Proposal.pdf),
[requirements register](../requirements/REQUIREMENTS.md) and
[architecture conventions](../design/ARCHITECTURE.md).

## 2.2 Functional requirements

### 2.2.1 Reservation

Table 2.1. Reservation requirements (Objective a, with the conflict guarantee in Objective d).

| ID | Requirement | Priority |
|---|---|---|
| FR-RES-01 | Show available tables and slots for a future date, including table label, capacity and zone. | Must |
| FR-RES-02 | Place a 10-minute `HELD` reservation and switch it to `CONFIRMED` on explicit customer confirmation. | Must |
| FR-RES-03 | Allow one active reservation per table and slot. A competing request receives `20001` and creates no additional row. | Must |
| FR-RES-04 | Release expired holds and exclude them from occupancy even when scheduled cleanup is unavailable. | Must |
| FR-RES-05 | Enforce `HELD → CONFIRMED → SEATED → COMPLETED` and the allowed branches to `CANCELLED`, `NO_SHOW` and `EXPIRED`. Reject an illegal transition with `20003`. | Must |
| FR-RES-06 | Let staff list all reservations and change status. Customers can list and cancel their own. | Must |
| FR-RES-07 | Record `NO_SHOW` as a separate terminal state so analytics can distinguish it from cancellation. | Must |
| FR-RES-08 | Record the actor, before/after state and request identifier for every reservation write. | Must |

### 2.2.2 Ordering

Table 2.2. Ordering requirements (Objectives a and b).

| ID | Requirement | Priority |
|---|---|---|
| FR-ORD-01 | Display menu dishes by category with name, description, price and availability. | Must |
| FR-ORD-02 | Allow a customer with an active reservation to submit an order attached to that reservation. | Must |
| FR-ORD-03 | Preserve the price charged on each order line when the menu price changes later. | Must |
| FR-ORD-04 | Let staff list live orders and apply the permitted transitions through `PENDING`, `ACCEPTED`, `PREPARING`, `SERVED` and `COMPLETED`, including permitted cancellation. | Must |
| FR-ORD-05 | Publish the completion event that triggers points earning and unlocks review eligibility for the dishes in that order. | Must |

### 2.2.3 Membership & Loyalty

Table 2.3. Membership and loyalty requirements (Objective c).

| ID | Requirement | Priority |
|---|---|---|
| FR-MEM-01 | Support public customer registration and sign-in for the four roles, with a 60-minute access token and a seven-day refresh session. | Must |
| FR-MEM-02 | Enforce role and resource ownership at protected endpoints. A valid session with insufficient permissions receives `403 / 30003`. | Must |
| FR-MEM-03 | Record `EARN`, `REDEEM`, `EXPIRE` and `ADJUST` in an append-only ledger and derive the available balance from eligible entries. | Must |
| FR-MEM-04 | Assign `BRONZE`, `SILVER`, `GOLD` and `PLATINUM` using agreed tier thresholds. | Should |
| FR-MEM-05 | Enforce `EXCLUSIVE` and `STACKABLE` coupon policies with an agreed evaluation order. | Should |
| FR-MEM-06 | Audit every points adjustment, coupon issue or redemption, and account role change. | Must |

M10 owns authentication, role enforcement and role-change auditing. M4 owns the
ledger, tier and coupon functions and their audit events. The shared boundary is the
verified account identifier, which connects the customer's session with the loyalty
records. Chapter 8 explains the delivered authentication flow and the loyalty handoff.

### 2.2.4 Ratings & Reviews

Table 2.4. Review requirements (Objective c).

| ID | Requirement | Priority |
|---|---|---|
| FR-REV-01 | Accept a review only from the customer of a completed order containing the dish. | Must |
| FR-REV-02 | Permit a single review for each dish, customer and order combination. | Must |
| FR-REV-03 | Rank dishes with Bayesian averages so sparse rating samples have less influence than well-supported ratings. | Must |
| FR-REV-04 | Limit review submission, by default to five per minute per user, and record limit hits. | Must |
| FR-REV-05 | Hold new reviews as `PENDING` for staff moderation. Keep rejected reviews out of public results. | Must |

### 2.2.5 Analytics

Table 2.5. Analytics requirements (Objective e).

| ID | Requirement | Priority |
|---|---|---|
| FR-ANA-01 | Chart revenue trends over a selectable date range. | Must |
| FR-ANA-02 | Show seatings per table per day. | Must |
| FR-ANA-03 | Show demand by day of week and hour. | Must |
| FR-ANA-04 | Calculate no-show rate as `NO_SHOW / (NO_SHOW + COMPLETED)` for the selected range. | Must |
| FR-ANA-05 | Provide a hybrid dish recommender and evaluate it offline with Precision@K and MAE. | Should |

### 2.2.6 Cross-cutting requirements

Table 2.6. Shared service requirements (Objective f).

| ID | Requirement | Priority |
|---|---|---|
| FR-XX-01 | Use the common envelope (`code`, `message`, `data`, `request_id`, `timestamp`) and the agreed five-digit failure codes. | Must |
| FR-XX-02 | Correlate the `X-Request-ID` response header, application log and audit entries for the same request. | Must |
| FR-XX-03 | Audit back-office mutations with before/after snapshots for the affected resource. | Must |
| FR-XX-04 | Generate OpenAPI from the running application and archive an updated snapshot after route changes. | Must |

The HTTP status indicates the outcome at the protocol level and the application
code identifies the business case. For example, both a booking conflict and a stale
edit may return HTTP 409. Application code `20001` tells the client to select another
slot, while `20004` tells it to reload the record before retrying.

## 2.3 Non-functional requirements

Table 2.7. System qualities and available verification artefacts, checked against
the 23 November main baseline (`7d08e38`). Chapter 12 records test run outcomes.

| ID | Acceptance requirement | Verification artefact and limits |
|---|---|---|
| NFR-01 | For at least 50 concurrent requests on one slot, return one `code 0`, all others `20001`, and persist one active reservation. Repeat the result ten times on MySQL. | `tests/concurrency/test_concurrent_booking.py` exists. At this baseline it requests 10 workers for 5 runs, lacks the selector used by the integration job and does not send customer authentication. The full acceptance result is pending. |
| NFR-02 | At least 80% unit coverage of `src/` at submission. Run integration and concurrency tests against MySQL 8. | `.github/workflows/ci.yml` runs the coverage gate and provisions MySQL. `tests/integration/test_ordering_mysql.py` is a skipped placeholder at this baseline. PR #10 ran real authentication cases. This follow-up restores the membership MySQL suite, which needs a fresh CI run. |
| NFR-03 | Run hygiene, lint, types, dependency/security checks, unit, integration, frontend and container checks on pull requests. Require the aggregate check to pass. | `.github/workflows/ci.yml`, the `CI passed` job and the `protect-main` ruleset documented in Chapter 11. The membership frontend also has its own workflow. |
| NFR-04 | Parameterise queries, hash passwords with bcrypt cost at least 12, configure secrets outside source, restrict production CORS/docs, limit review requests, and run the container as a non-root user. | CI Bandit and pip-audit, `tests/unit/test_security.py`, `tests/unit/test_config.py`, and the checked-in deployment files cover specific controls. The review limiter is wired on main; per-account limiting and limit-hit recording still require evidence. |
| NFR-05 | Keep audit rows across process restarts. Redact credentials and permit application code to append audit events. | `tests/unit/test_audit.py`, and account change/rollback cases in the membership API and MySQL suites. State-change coverage across modules is tracked in Chapter 11. |
| NFR-06 | Start the API and MySQL with Docker Compose, apply migrations on startup and return HTTP 200 from the health endpoint. | `INSTALL.md` and `deploy/docker/` describe the full startup. CI runs a container health smoke test and a separate MySQL migration job; a health response alone does not exercise the full Compose startup. |
| NFR-07 | Use MySQL 8 InnoDB and `utf8mb4`, configure `READ COMMITTED` at the connection and server levels, and provide reversible Alembic migrations. | `src/data/database.py`, `deploy/docker/`, the MySQL migration step in CI and `tests/unit/test_migration_completeness.py`. The CI MySQL service's global default can differ from the application's connection setting. |
| NFR-08 | Archive the REST contract in OpenAPI and document installation and use of all five modules. | `scripts/export_openapi.py`, `docs/api/openapi.json`, `INSTALL.md` and the instructions in `docs/user-manual/`. Coverage of all five modules remains a deliverable for the user-manual owner. |
| NFR-09 | Limit list page sizes to 100 and report `10002` for invalid pagination. Use aggregate reads on the dashboard path. | Pagination helpers and `tests/unit/test_api_contract.py` verify the shared envelope and bounds; member and order endpoint tests exercise specific callers. Dashboard data evidence belongs in Chapters 10 and 12. |

### 2.3.1 Security requirements (OWASP Top 10)

At the access boundary (A01), every protected request must verify its session and
enforce the role and ownership rules in Table 2.8. The identity used by a service
must come from the verified session. This matters for bookings, orders and reviews,
where a client can submit an identifier for a different account. Account changes
and session revocation are checked in the membership API and cross-module behaviour
is checked using sessions issued by real login requests.

Cryptographic controls (A02) require bcrypt with a work factor of at least 12,
environment-supplied signing material and secure cookie flags in production.
Transactions use parameterised queries (A03). The common envelope and scoped
operations help make expected failures usable without disclosing internals (A04).
Production configuration requires explicit allowed origins and disables interactive
API documentation (A05). Continuous integration checks dependency advisories and
common unsafe Python patterns (A06).

Authentication controls (A07) include short-lived access tokens, session expiry and
revocation, refresh rotation and rate limits. Data integrity (A08) requires testing
the same migration chain used for deployment. Logging (A09) requires traceable,
redacted audit events at state-change boundaries. The current scope contains no
endpoint that fetches an arbitrary user-supplied URL, so the SSRF category (A10) has
no corresponding feature requirement. Chapter 11 contains the full control mapping
and tracks controls requiring additional evidence.

### 2.3.2 Performance, reliability and data requirements

Order and reservation records must stay consistent when multiple users act at once.
The governing reservation invariant is one active row per table and slot, even when
the check for an available slot overlaps another request. The storage strategy and
its transaction boundaries are described in Chapters 4–6. A database rollback is
also tested separately from an application rollback, since these operate at different
boundaries and neither establishes that a data-destructive downgrade preserves data.

The page-size limit bounds the number of records moved for one list request and gives
the interface predictable navigation. Analytics requests should consume aggregates
with consistent date and status definitions. A predictable HTTP response and a
matching request identifier help a user recover from a stale edit or give the team
enough information to pinpoint a failure without sharing sensitive fields.

## 2.4 Role-permission matrix

Table 2.8. Server-side permission requirements (handbook §4.4, actor definitions
in the requirements register §2). “Own” means the server verifies resource ownership.
The matrix states the intended permissions, including routes at differing stages of
delivery. Chapters 3, 7 and 8 use these same role boundaries.

| Endpoint group | Public | Customer | Waiter | Manager | Admin |
|---|---|---|---|---|---|
| Registration and sign-in | Yes | Yes | Yes | Yes | Yes |
| Session renewal and logout | Session cookie and CSRF proof as applicable | Own | Own | Own | Own |
| Current identity and personal profile | — | Own | Own | Own | Own |
| Customer booking, orders, review creation and loyalty actions | — | Own | — | — | — |
| Staff reservation/order operations and review moderation | — | — | Yes | Yes | Yes |
| Management dashboard, audit queries and loyalty configuration | — | — | — | Yes | Yes |
| User creation, role changes and account status administration | — | — | — | — | Yes |
| Public dish rankings | Yes | Yes | Yes | Yes | Yes |

Public registration always assigns the customer role. Staff accounts are created
through an authorised administrator. A missing credential returns `401 / 30001`,
and an invalid, expired or revoked credential returns `401 / 30002`. A verified
session whose role or ownership does not permit the requested action returns
`403 / 30003`. Each protected endpoint declares its allowed roles. Manager and
administrator permissions cover staff operations where their roles are on that list.
The completed-order check applies to an otherwise authorised review submission.

## 2.5 Traceability

Table 2.9. Proposal objectives, requirement records and evidence. The test paths
point to inspectable artefacts. A partial result is marked where applicable.

| Objective | Requirements | Evidence and remaining acceptance | Owner |
|---|---|---|---|
| (a) Customer reservation and ordering | FR-RES-01/02/04/05, FR-ORD-01/02/03 | `test_reservation_repository.py` and `test_ordering_api.py` provide module-level cases. Seven-state booking and slot availability are in M2's PR #34. Table catalogue attributes and the customer order ownership flow need further verification. | M2, M5 |
| (b) Staff backend | FR-RES-06, FR-ORD-04 | `test_staff_api.py` and `test_membership_authorization.py` cover role boundaries and staff route behaviour. Main contains the staff-to-order-service wiring. | M3, M5 |
| (c) Membership, loyalty and reviews | FR-MEM-01–06, FR-REV-01–05 | `test_membership_api.py`, `test_membership_authorization.py`, `test_membership_schema.py`, `test_review_schema.py` and `test_review_submission.py`. PR #10 provides historical MySQL authentication evidence. Current MySQL authentication re-verification, complete loyalty integration and completed-order review eligibility remain separate checks. | M10, M4, M9 |
| (d) Database concurrency and testing | FR-RES-03, NFR-01/02 | `test_migration_completeness.py`, CI coverage and `tests/concurrency/test_concurrent_booking.py`. The production-dialect booking race at the required scale remains open. | M8, M4, M7 |
| (e) Analytics and recommendations | FR-ANA-01–05, NFR-09 | The manager dashboard and analytics service exist in main. The manager access boundary, seed-backed aggregation and offline Precision@K/MAE results remain to be demonstrated. | M6 |
| (f) Engineering quality | FR-XX-01–04, NFR-02–08 | CI workflow, audit and API contract tests, model/migration checks, OpenAPI snapshot, user manual and engineering controls in Chapter 11. | M1 and module owners |
| (g) Proposal, updates and presentation | Submitted proposal and project updates | Archived proposal, project-update materials and presentation deliverables as scheduled. | M1, M4, M6, M7 |

## 2.6 Requirements changes during the project

The team fixed a 30-minute slot grid, moderation before publication and an
append-only points ledger. M2's seven-state reservation change replaces a single
timestamp with a date and slot start and distinguishes a temporary hold from a
confirmed booking. The purpose is to make expiry, conflict checking and no-show
reporting testable. The pull request for that implementation is separate from the
main baseline and the permissions tests must follow the accepted contract.

The team kept the four actor roles and clarified how they are provisioned. A public
registration creates a customer, while an administrator controls staff accounts.
Role or account-status changes invalidate the old sessions. This preserves the role
matrix while closing the case where a previously issued token outlives an account's
permissions. The authentication scope and its audit evidence are in Chapter 8.

The points and coupon rules remain open in the requirements register (§6). The
group's proposed award is one point for every full ¥10 spent, expiring after 12
months. The uploaded loyalty prototype uses the same earn rate and a **365-day**
lifetime, so examples that cross a leap day can differ from a 12-calendar-month
policy. For coupons, the proposal and prototype put percentage discounts before
fixed-amount discounts, cap the total at the subtotal and prohibit combining
`EXCLUSIVE` coupons. They remain proposals for the group contract. M4 and M10 should
record the confirmed points expiry convention and coupon order in the shared
contract before the group accepts either rule. Chapter 8 distinguishes this prototype
evidence from a route callable in the running app.

Maximum table occupation, Bayesian confidence, hybrid weighting and the operational
definition of a no-show are also open in the register. A state enum and the no-show
rate formula leave room for the policy decision about when a late guest becomes a
no-show. The register's proposed thresholds are distinct from verified defaults.
Chapter 13 tracks remaining decisions and delivery gaps for the final review.
