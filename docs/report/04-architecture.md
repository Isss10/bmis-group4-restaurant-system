<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: M8
  TARGET: 8–9 pages        DUE: 23 Nov 2026
  STATUS: not started
  SOURCES: docs/design/ARCHITECTURE.md (three-tier rationale §1, tier overview §2,
           dependency rule §3, shared boundaries §6, open questions §13),
           docs/api/openapi.json, docs/requirements/REQUIREMENTS.md §3
  RULE: no source code. Describe and explain only — use diagrams and pseudocode.
-->

# 4. System Design & Architecture

> **This is the longest chapter M1 owns and the one the rubric weighs most heavily.** The
> marking criteria list **five** kinds of model and expect all five to appear. The checklist
> at the bottom of this file tracks them; none may be missing at merge time.
>
> `docs/design/ARCHITECTURE.md` is already a strong, committed document and supplies most of
> the content for §4.1–§4.3. Do not copy it wholesale — the report must *explain*, and the
> architecture document is written for developers, not for an examiner.

## 4.1 Architectural style and rationale

<!-- From ARCHITECTURE.md §1: why three-tier. The three reasons given there are good and
     specific — the concurrency guarantee has exactly one home, ten people can work in
     parallel, and the REST boundary is a natural test seam. Expand each with the
     consequence it had in practice on this project. -->

## 4.2 System context model  ★ rubric model 1 of 5

<!-- Figure 4.1. The system and its environment: customers, waiters, managers, admins, the
     hold-expiry job, MySQL. Show what crosses each boundary (HTTP/JSON with a JWT bearer
     token; SQL to the database). State what is deliberately outside: payment gateway, SMS,
     cloud services. -->

## 4.3 Three-tier architecture  ★ rubric model 2 of 5

<!-- Figure 4.2. Reproduce the tier diagram from ARCHITECTURE.md §2 as a proper figure.
     Describe each tier's responsibility and, critically, what it is forbidden to know:
     presentation knows HTTP but no business rules; application knows domain rules but no
     HTTP and no SQL dialect; data is the only tier that may contain SQL. -->

### 4.3.1 The dependency rule

<!-- From ARCHITECTURE.md §3, including the import matrix. Explain the enforcement
     mechanism (lint rules in CI) rather than merely stating the rule — an enforced rule is
     evidence of engineering quality for chapter 11. -->

## 4.4 Business process model  ★ rubric model 3 of 5

<!-- Figure 4.3. The end-to-end business flow: customer registers -> logs in -> browses
     availability -> books (hold created) -> confirms -> is seated -> orders -> order
     completes -> points awarded and review eligibility unlocked -> customer reviews ->
     moderation -> ranking updated -> analytics aggregates the whole history.
     This is the diagram that shows the five modules are one system and not five demos. -->

## 4.5 Class / domain model  ★ rubric model 4 of 5

<!-- Figure 4.4. The domain classes and their relationships: Reservation, Table, TimeSlot,
     Order, OrderItem, Dish, Customer, PointsLedgerEntry, Coupon, MembershipTier, Review,
     AuditLog. Show cardinalities. Derive from src/data/schema/ and the migration chain, but
     PRESENT IT AS A MODEL, not as a table listing — chapter 5 covers the physical schema.
     Coordinate with M8 so chapters 4 and 5 are the logical and physical views of the same
     model and do not contradict each other. -->

## 4.6 Sequence models  ★ rubric model 5 of 5

<!-- At least three, and the first is non-negotiable because it is the project's central
     claim:
       Figure 4.5 — CONCURRENT BOOKING. Two customers POST the same table and slot at the
                    same instant. Show the transaction boundary, the version check, the
                    unique-constraint violation, and the 20001 envelope reaching the loser.
                    This single diagram carries Objective (d) and is also the best slide in
                    the presentation.
       Figure 4.6 — Order completion fan-out: order reaches COMPLETED, the event awards
                    points and unlocks review eligibility (FR-ORD-05).
       Figure 4.7 — Authentication and authorisation: login issues access and refresh
                    tokens; a subsequent request is checked against the role matrix, and a
                    wrong-role token yields 30003 rather than a 401. -->

## 4.7 API design

<!-- The REST conventions: the frozen base paths per module (/api/v1/reservations,
     /orders, /staff, /membership, /reviews, /analytics), the response envelope
     code/message/data/request_id/timestamp, the five-digit error-code families, X-Request-ID
     correlation across response header, application log and audit row, ISO 8601 UTC
     timestamps, and bounded pagination. Summarise the surface from docs/api/openapi.json —
     DO NOT print the JSON. A table of endpoint groups with their owning module and required
     role is enough. -->

## 4.8 Data design overview

<!-- One paragraph orienting the reader, then hand off to chapter 5. Keep the physical
     schema out of this chapter. -->

## 4.9 Frontend architecture

<!-- Three Vue 3 + Vite + TypeScript single-page clients (customer, staff, manager) built
     separately and served as static assets. Describe the component structure and how the
     client talks to the API through the envelope contract. -->

## 4.10 Deployment architecture

<!-- Docker: MySQL 8.0 plus the API, migrations applied automatically on start, /health as
     the readiness signal, non-root container user. Describe the compose topology; chapter 11
     covers the CI pipeline that builds it. -->

## 4.11 Design decisions and trade-offs

<!-- The rubric rewards justified decisions, not just described ones. Candidates, all
     already argued somewhere in the repo — collect and defend them here:
       - Why three separate concurrency defences instead of one (cross-ref ch.5).
       - Why an explicit READ COMMITTED isolation level set per session AND at server level
         instead of relying on the MySQL default (NFR-07).
       - Why an append-only points ledger instead of a mutable balance column (FR-MEM-03).
       - Why a Bayesian average instead of a plain mean (FR-REV-03).
       - Why NO_SHOW is its own terminal state (FR-RES-07, needed by FR-ANA-04).
       - Why module routers are loaded by a registry that tolerates a missing module — this
         let ten people merge in parallel, and it is why an unimplemented module does not
         break the whole app. -->

---

## ★ The five-model checklist — all must be present at merge time

- [ ] 4.2 System context model — Figure 4.1
- [ ] 4.3 Three-tier architecture — Figure 4.2
- [ ] 4.4 Business process model — Figure 4.3
- [ ] 4.5 Class / domain model — Figure 4.4
- [ ] 4.6 Sequence models — Figures 4.5, 4.6, 4.7 (at least one, ideally three)

## Other notes — to resolve before merging

- [ ] **§4.9 claims three Vue clients.** Verify the manager dashboard client exists. As of
      14 Nov the repo has `frontend/` (customer) and `src/presentation/membership/` — the
      staff and manager surfaces may not be separate apps. **Describe what ships**, not the
      plan; chapter 1 flags the same risk.
- [ ] **§4.7 must match the deployed routes.** The router registry in
      `src/presentation/api/main.py` declares six module prefixes, but the loader skips a
      module whose file does not exist. As of 14 Nov `routers/ordering.py` and
      `routers/analytics.py` are absent, so `/api/v1/orders` and `/api/v1/analytics` are
      declared but not mounted. Do not document them as available until they are.
      Regenerate `docs/api/openapi.json` from the running app before writing this section
      (FR-XX-04 requires this anyway).
- [ ] §4.5 must be reconciled with M8's chapter 5 — logical model here, physical schema
      there, same entities, no contradictions.
- [ ] §4.6's concurrent-booking sequence is also the centrepiece of the presentation. Build
      it once, well, and let M4/M6 reuse the exported figure in the slides.
