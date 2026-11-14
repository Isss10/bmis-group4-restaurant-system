<!--
  AUTHOR: M3 (RANXI HE)   SUPPORT: —
  TARGET: 3 pages         DUE: 27 Nov 2026
  STATUS: not started
  SOURCES: src/application/staff_service.py, src/presentation/api/routers/staff.py,
           docs/requirements/REQUIREMENTS.md §4.1 FR-RES-06, §4.2 FR-ORD-04,
           manual §4.4 (role matrix)
  RULE: no source code. Screenshots, flowcharts and prose.
-->

# 7. Implementation — Staff Backend

## 7.1 Purpose and audience

<!-- The back office used by waiters, managers and admins. Distinguish it from the customer
     app: different actor, different permissions, different tasks. -->

## 7.2 Interface design

<!-- Screenshots of the reservation list, the order list and the status-change controls.
     Explain the layout rationale briefly — this chapter is short and visual by design. -->

## 7.3 Reservation management (FR-RES-06)

<!-- Listing all reservations, filtering, and advancing status through the state machine.
     The status change must validate the transition (ch.6 §6.6) and return 20003 on an
     illegal one. Marking NO_SHOW as a distinct action. -->

## 7.4 Order management (FR-ORD-04)

<!-- Viewing the food-order list and advancing PENDING -> ACCEPTED -> PREPARING -> SERVED ->
     COMPLETED, or CANCELLED. Note that reaching COMPLETED triggers the event consumed by
     ch.8 and ch.9. -->

## 7.5 Authorisation in the back office

<!-- How the staff identity is established from the token and how the role matrix is
     enforced server-side. A waiter must not reach manager-only functions; the client hiding
     a button is not the control — the API rejecting the call is. Cross-reference ch.8 and
     ch.11. -->

## 7.6 Audit trail from the back office

<!-- Every status change here writes an audit row (FR-XX-03). Show one worked example:
     who, what, before/after, request id. Cross-reference ch.11 for the subsystem. -->

---

## Author's notes — to resolve before merging

- [ ] **The staff service currently returns hardcoded data.** As of 14 Nov, on `main`,
      `src/application/staff_service.py` returns literal fixtures — a single fake
      reservation `{"id": 1, "status": "booked", "table_id": 5}` and a single fake order
      `{"id": 101, "items": ["pizza"], "status": "pending"}` — and its status-update methods
      return a canned success message without touching the database. The router mounts, so
      the endpoints respond 200, which is worse than failing: **it looks working and is
      not.** Your proposal deadline for the reservation-list display module was 20 Nov and
      for integration 23 Nov.
      Until this reads real data you have no screenshots to put in §7.2 and nothing truthful
      to write in §7.3–§7.4. M1 has raised it with the group on 14 Nov.
- [ ] §7.5 is where you can earn marks cheaply: explaining that authorisation is enforced
      server-side and not by hiding UI elements is exactly the kind of technical reasoning
      the rubric rewards. Do not skip it for want of screenshots.
- [ ] Only 3 pages are budgeted. Do not expand this chapter by padding §7.2 — if you have
      more to say about the reservation state machine it belongs in ch.6, and about
      authorisation in ch.8.
