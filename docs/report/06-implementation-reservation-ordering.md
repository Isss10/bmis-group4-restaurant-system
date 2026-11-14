<!--
  AUTHOR: M2 (KEYING CHEN)   SUPPORT: M5
  TARGET: 4–5 pages          DUE: 27 Nov 2026
  STATUS: not started
  SOURCES: src/application/reservation/, src/presentation/api/routers/reservation.py,
           docs/requirements/REQUIREMENTS.md §4.1–4.2, manual §4.5 (state machine),
           §5.3 (three-layer booking defence)
  RULE: no source code. Pseudocode, flowcharts and prose only.
-->

# 6. Implementation — Reservation & Ordering

## 6.1 Module responsibilities and boundaries

<!-- What this module owns, what it exposes to others, and what it must not touch. The
     application tier is pure Python with no HTTP and no SQL dialect knowledge — say what
     that bought you when testing. -->

## 6.2 Availability browsing (FR-RES-01)

<!-- How free slots are computed for a future date: the slot grid, which reservation states
     count as occupying, and how an EXPIRED hold is excluded so a dead hold does not block a
     real booking. Present as a flowchart or pseudocode. -->

## 6.3 Creating a reservation (FR-RES-02)

<!-- The HELD state, hold_expires_at = now + 10 minutes, and confirmation into CONFIRMED
     only on explicit customer action. Pseudocode for the create flow. -->

## 6.4 Conflict detection under concurrency (FR-RES-03)  ★ the core of this chapter

<!-- The critical section: transaction, optimistic version check, unique constraint. Refer
     to ch.5 §5.5 for the schema-level defence and explain here what the SERVICE does.
     The contract: a concurrent second request fails with 20001 and never produces a
     duplicate row. Describe how the database's constraint violation is caught and
     translated into the frozen envelope rather than surfacing as a 500.
     Pseudocode only — no source. -->

## 6.5 Hold expiry (FR-RES-04)

<!-- The background job that expires stale holds every 60 seconds, and — more importantly —
     why correctness does NOT depend on that job being alive: the availability query itself
     must treat an expired hold as non-occupying. Explain the two mechanisms and why the
     query-side check is the one that actually guarantees correctness. -->

## 6.6 The reservation state machine (FR-RES-05, FR-RES-07)

<!-- HELD -> CONFIRMED -> SEATED -> COMPLETED, plus CANCELLED, NO_SHOW, EXPIRED. The legal
     transitions are held in an explicit allowed-transition table (manual §4.5 requires this)
     and an illegal transition returns 20003. Reproduce the transition table and the state
     diagram is in ch.3 §3.5 — cross-reference, do not redraw.
     Explain why NO_SHOW is its own terminal state rather than a variant of CANCELLED:
     FR-ANA-04 computes no-show rate as NO_SHOW / (NO_SHOW + COMPLETED), which is impossible
     if the two are collapsed. -->

## 6.7 Staff operations on reservations (FR-RES-06)

<!-- Waiter/manager/admin list all reservations and change status; a customer may list and
     cancel only their own. How ownership is enforced — derived from the token, never from a
     client-supplied user id — and what a wrong-role token returns (30003). -->

## 6.8 Auditing reservation writes (FR-RES-08)

<!-- Every write produces an audit row naming the actor, the before/after status and the
     request id. Cross-reference ch.11 for the audit subsystem; here explain what this
     module records and when. -->

## 6.9 Menu browsing and dish detail (FR-ORD-01)

<!-- Category grouping, dish name, description, price, availability. -->

## 6.10 Submitting an order (FR-ORD-02, FR-ORD-03)

<!-- The order must attach to an active reservation. Explain the PRICE SNAPSHOT rule: each
     dish's price is copied into the order item at order time, so a later menu change cannot
     alter an existing order. This is a genuine data-integrity argument and a good place to
     show technical depth — explain what breaks if you store only a foreign key to the dish. -->

## 6.11 Order lifecycle and the completion event (FR-ORD-04, FR-ORD-05)

<!-- PENDING -> ACCEPTED -> PREPARING -> SERVED -> COMPLETED, or CANCELLED. On reaching
     COMPLETED the module emits the event that (a) awards loyalty points and (b) unlocks
     review eligibility for the ordered dishes. Explain the coupling: ch.8 and ch.9 both
     consume this event, and neither may reach into the ordering tables directly. -->

---

## Author's notes — to resolve before merging

- [ ] **Most of this chapter describes code that does not exist yet.** As of 14 Nov, on
      `main`:
        - `routers/ordering.py` is **absent**. The router registry declares
          `/api/v1/orders` but the loader skips a missing module, so the endpoint is not
          mounted. PR #18 delivered the customer-side ordering **UI** (category filter,
          cart, order submission) but there is no backend behind it.
        - The reservation service implements only `create_reservation` and
          `cancel_reservation`. There is **no conflict detection, no state machine, no
          allowed-transition table, no hold expiry**.
        - The reservations table has **no version column and no unique constraint**, so the
          20001 path has nothing to trigger it.
      Your proposal deadline for the seat-time conflict-checking algorithm was 2 Nov and for
      order submission 15 Nov. **This chapter cannot be written honestly until the code
      lands.** M1 has raised it with the group on 14 Nov; please reply with a date.
- [ ] §6.4 and §6.6 are the two sections the examiner will read most closely, because they
      carry Objective (d). If the implementation is not finished by 27 Nov, write them as
      design and say so — an honest "specified, not yet demonstrated" costs less than a
      claim chapter 12 contradicts.
- [ ] Coordinate §6.11's completion event with M10 (ch.8, points) and M9 (ch.9, review
      eligibility) so all three describe the same event and the same payload.
- [ ] Pseudocode is allowed and encouraged; source code is forbidden. A flowchart of the
      booking critical section is worth more marks than a code listing would be.
