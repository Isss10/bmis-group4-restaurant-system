<!--
  AUTHOR: M10 (RONG CONG)   SUPPORT: M4
  TARGET: 4 pages           DUE: 27 Nov 2026
  STATUS: not started
  SOURCES: src/application/membership/service.py, src/presentation/api/routers/membership.py,
           src/data/schema/membership.py, src/data/repository/membership.py,
           migration 0004_add_membership_auth.py, docs/design/MEMBERSHIP_MEMBER10.md,
           docs/api/MEMBERSHIP_AUTH.md, docs/requirements/REQUIREMENTS.md §4.3
  RULE: no source code. Pseudocode, tables and prose.
-->

# 8. Implementation — Membership & Loyalty

> **This module is the most complete on `main`.** It has a service layer, a router, ORM
> schema, a repository, its own migration, four test files (API, authorisation, schema, plus
> MySQL integration), a dedicated frontend with its own CI workflow, and two design
> documents. Much of this chapter can be assembled from `MEMBERSHIP_MEMBER10.md` and
> `MEMBERSHIP_AUTH.md` — but **explain, do not transcribe**, and remember the report is for
> an examiner, not for a developer.

## 8.1 Registration and authentication (FR-MEM-01)

<!-- The four frozen roles; a 60-minute access token and a 7-day refresh token. Explain the
     token lifecycle, what each token is for, and the refresh flow. Password hashing with
     bcrypt at cost >= 12 (NFR-04) — explain the cost choice, do not paste the call. -->

## 8.2 Role-based access control (FR-MEM-02)

<!-- The frozen role-permission matrix enforced server-side on every endpoint. The specific
     contract worth calling out: a VALID token carrying the WRONG role yields 30003, never a
     401 — conflating "who are you" with "you may not" is a common API design defect and
     this project deliberately avoids it. Sequence diagram is in ch.4 §4.6; cross-reference. -->

## 8.3 The append-only points ledger (FR-MEM-03)  ★ strongest technical point

<!-- EARN / REDEEM / EXPIRE / ADJUST entries, appended and never edited. Balances are DERIVED
     by summing unexpired entries; there is no mutable balance column.
     Explain WHY: a mutable balance is a lost-update hazard under concurrency and leaves no
     history to audit; an append-only ledger is idempotent to re-read, gives a complete audit
     trail for free, and makes expiry computable rather than something that has to be
     remembered. This is a real design trade-off and exactly what "Technical Depth" means —
     give it a full page. -->

## 8.4 Membership tiers (FR-MEM-04)

<!-- BRONZE / SILVER / GOLD / PLATINUM with the contract's thresholds. Explain how a tier is
     determined and when it is recomputed. -->

## 8.5 Coupons and discount stacking (FR-MEM-05)

<!-- EXCLUSIVE versus STACKABLE, and the evaluation ORDER of stacked discounts — which must
     be defined in the contract and tested, because applying a percentage before a fixed
     amount gives a different total than the reverse. Give a worked numeric example. -->

## 8.6 Auditing membership changes (FR-MEM-06)

<!-- Every points adjustment, coupon issue and redemption, and role change writes an audit
     row. Cross-reference ch.11 for the subsystem; describe what this module records. -->

## 8.7 Frontend

<!-- The membership client under src/presentation/membership/ with its own TypeScript auth
     module, its own test file and its own CI workflow. Explain how it stores and presents
     tokens, and how it handles expiry. -->

---

## Author's notes — to resolve before merging

- [ ] **Two of your business rules were never confirmed as decided.**
      `REQUIREMENTS.md` §6 lists the points **earning rate and expiry window** (proposed:
      1 point per ¥10, expiring 12 months after earning) and the coupon **stacking order**
      (proposed: EXCLUSIVE never combine; among STACKABLE apply percentage first then fixed
      amount, capped at the order total) as **open**, both with a 20 Oct deadline. §8.3–§8.5
      cannot be written concretely without them. Confirm what the code actually does, write
      that, and get the agreed value written back into the contract by PR — that PR is the
      only legitimate way to change a frozen value.
- [ ] §8.4 tiers are priority **Should**, not Must. If they are not implemented, say so and
      move them to ch.13 Future Work. A Should that is honestly deferred costs nothing; a
      Should claimed and not delivered costs credibility across the whole report.
- [ ] You also own chapter 2. **Agree with M1 where the OWASP table lives** (ch.2 §2.3.1
      summarises, ch.11 gives it in full) before either of you writes it.
- [ ] Do not print `openapi.json` or the router code. Summarise the endpoint surface in a
      table: path, method, required role, purpose.
