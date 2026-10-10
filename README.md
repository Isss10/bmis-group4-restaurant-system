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

- Three-tier architecture with a **documented REST API**
- Unit / integration / concurrency tests with **coverage reports**
- **CI running on every pull request**
- **OWASP Top 10** hardening
- **Audit logs** for back-office changes
- **Docker** deployment
- A **user manual** covering all modules

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

> The directories currently contain only `.gitkeep` placeholders. Replace them with real code as
> each module is developed.

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

**Never push directly to `main`.** `main` is protected and always deployable.

---

## 8. Getting started

```bash
git clone git@github.com:Isss10/bmis-group4-restaurant-system.git
cd bmis-group4-restaurant-system
git checkout -b feature/your-module
```

Detailed setup instructions (database, dependencies, Docker) will be added to
[`docs/user-manual/`](docs/user-manual/) as the prototype takes shape.
