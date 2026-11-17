<!--
  AUTHOR: M9 (RUNYI PENG)   SUPPORT: —
  TARGET: 3–4 pages         DUE: 27 Nov 2026
  SOURCES: src/application/review/service.py, src/application/review/schemas.py,
           src/presentation/api/routers/review.py, migration
           0001_add_review_moderation_and_rating_stats_tables.py,
           docs/requirements/REQUIREMENTS.md §4.4, tests/unit/test_review_submission.py
  STATUS: not started
  RULE: no source code. The formula, pseudocode and a worked example.
-->

# 9. Implementation — Ratings & Reviews

## 9.1 Order-verified review submission (FR-REV-01)

<!-- A review is accepted only from a customer whose COMPLETED order contains the reviewed
     dish; anyone else receives the not-order-verified error. Explain how eligibility is
     established — via the order-completion event from ch.6 §6.11 — and why this matters:
     it is what makes the ranking trustworthy rather than a popularity contest open to
     anyone. This is the project's answer to fake reviews and belongs in the introduction's
     problem statement too. -->

## 9.2 Duplicate prevention (FR-REV-02)

<!-- The unique (dish_id, customer_id, order_id) triple. Explain why the ORDER is part of
     the key: a customer who orders the same dish twice on separate orders should be able to
     review it twice, but never twice for the same order. A uniqueness constraint enforces
     this at the database level rather than relying on an application check that a concurrent
     pair of requests could both pass. -->

## 9.3 Bayesian-average ranking (FR-REV-03)  ★ the showcase of this chapter

<!-- THE MARKED HIGHLIGHT. Manual §8.2 says to write this in detail, and it is the clearest
     piece of algorithmic depth the project has. Cover:

       1. The problem with a plain mean. A new dish with one 5-star review has a mean of
          5.0 and would outrank a signature dish with 200 reviews averaging 4.8. That is
          obviously wrong and is the reason the requirement exists.
       2. The formula. Present the Bayesian average with the prior mean C and the confidence
          weight m, define every symbol, and explain the intuition: each item starts at the
          global average with m imaginary votes, and real votes pull it away in proportion to
          how many there are.
       3. How C is computed and how often it is recomputed (nightly, per the proposal).
       4. The value of m and WHY that value. m = 15 was the proposed figure — confirm what
          the code uses and justify it. Explain the trade-off: a large m flattens genuine
          differences between heavily reviewed dishes; a small m lets a handful of reviews
          dominate.
       5. A WORKED NUMERIC EXAMPLE with two or three dishes showing plain mean versus
          Bayesian average and the resulting rank change. A small table here is worth more
          than a page of prose.
       6. Where the computed value is stored — the rating_stats table from migration 0001 —
          and why precomputing it matters for the list endpoints (NFR-09: the dashboard and
          ranking read aggregates, not raw tables).

     Derive the formula; do not paste code. -->

## 9.4 Rate limiting (FR-REV-04)

<!-- Default 5 submissions per minute per user, with limit hits recorded. Explain what the
     limit defends against (review spam, and a single user distorting a dish's ranking) and
     how a hit is surfaced. NFR-04 lists rate limiting among the OWASP hardening controls —
     cross-reference ch.11. -->

## 9.5 Moderation queue (FR-REV-05)

<!-- New reviews are held in PENDING until a waiter or manager approves or rejects them;
     rejected reviews never appear publicly. Explain the state flow and that every
     moderation decision writes an audit row. -->

## 9.6 Interaction with the ordering module

<!-- The dependency on the order-completion event, stated once, with a cross-reference to
     ch.6 §6.11. This module must not read the ordering tables directly — say why (the
     dependency rule, ch.4 §4.3.1). -->

---

## Author's notes — to resolve before merging

- [ ] **Confirm the value of `m`.** `REQUIREMENTS.md` §6 lists the Bayesian confidence `m`
      as an **open** question with a 10 Nov deadline and a proposed value of 15. That
      deadline has passed. Check what the code actually uses, write that number, justify it
      in §9.3(4), and get it written back into the contract by PR. **An unjustified magic
      constant in the showcase algorithm is the kind of thing an examiner probes in the
      viva** — be ready to defend the number.
- [ ] Verify §9.3(6): confirm the precomputed statistic is really stored and really read by
      the ranking endpoint, rather than recomputed per request. If it is recomputed, say so
      and note it as a performance limitation for ch.13.
- [ ] §9.1 depends on the order-completion event from ch.6, and as of 14 Nov the ordering
      backend does not exist on `main`. Check whether review eligibility is actually wired to
      real orders or to a stub — `src/application/review/service.py` contains an
      `OrderServiceStub`. **Describe what is real.** A stub is acceptable in a PoC if the
      report says it is a stub.
- [ ] Keep to 3–4 pages. §9.3 is where the space should go; §9.4–§9.6 can each be a few
      paragraphs.
