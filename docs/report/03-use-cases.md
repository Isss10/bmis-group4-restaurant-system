<!--
  AUTHOR: M3 (RANXI HE)   SUPPORT: M2, M5
  TARGET: 6–7 pages       DUE: 20 Nov 2026
  STATUS: not started
  SOURCES: docs/requirements/REQUIREMENTS.md §2 (actors) and §3 (five Mermaid use-case
           diagrams, already drawn), §4 (FR tables)
  RULE: no source code. Describe and explain only.
-->

# 3. Use Cases & Requirements Modelling

> **Good news for the author:** the five use-case diagrams already exist as Mermaid source
> in `REQUIREMENTS.md` §3.1–3.5 (reservation, ordering, membership, reviews, analytics).
> They are committed and reviewed. Your job is to render them, explain them, and add the
> use-case **description tables** that the marking rubric explicitly asks for and that do
> not yet exist anywhere.

## 3.1 Modelling approach and notation

<!-- State the notation once: actors as stick figures, use cases as ellipses, «include» and
     «extend» as dashed arrows, the system boundary, and why the hold-expiry job is drawn as
     a system actor (it triggers behaviour with no user present). -->

## 3.2 Actors

<!-- The four human roles plus the system actor. Reference Table 2.x (role-permission
     matrix) rather than repeating it. Explain the actor hierarchy: admin > manager > waiter,
     and customer as the disjoint end-user role. -->

## 3.3 Use-case diagrams

### 3.3.1 Reservation module
<!-- Render REQUIREMENTS.md §3.1 as Figure 3.1. -->

### 3.3.2 Ordering module
<!-- Render §3.2 as Figure 3.2. Note the «extend» from order-completed to points awarding
     and to review eligibility — that cross-module coupling is worth a paragraph, it is the
     reason FR-ORD-05 exists. -->

### 3.3.3 Membership & Loyalty module
<!-- Render §3.3 as Figure 3.3. -->

### 3.3.4 Ratings & Reviews module
<!-- Render §3.4 as Figure 3.4. -->

### 3.3.5 Analytics module
<!-- Render §3.5 as Figure 3.5. Include the rule that the dashboard never writes
     cross-module SQL and consumes aggregates provided by the ordering and reservation
     modules. -->

## 3.4 Use-case descriptions

<!-- THIS IS THE PART THE RUBRIC ASKS FOR AND THE PART NOT YET WRITTEN.
     For each significant use case, a table with: use-case name and ID, primary actor,
     preconditions, postconditions, main success scenario (numbered steps), extensions and
     alternative flows (numbered, referencing the error codes), and the FR IDs it satisfies.

     Prioritise these, in this order — they carry the technical weight:
       1. Create reservation (UC2 §3.1) — must show the conflict extension returning 20001
          and the seat-hold «include». This is the project's central claim.
       2. Submit food order (UC3 §3.2) — price snapshotting and the order-completed event.
       3. Submit review (UC1 §3.4) — the order-verified precondition and rate limiting.
       4. Redeem coupon (UC4 §3.3) — stacking rules and the append-only ledger.
       5. Update reservation status (UC6 §3.1) — the state-machine validation and 20003.
     Then cover the remainder more briefly. -->

## 3.5 Reservation state machine

<!-- The rubric rewards this and manual §4.5 freezes it: HELD -> CONFIRMED -> SEATED ->
     COMPLETED, plus CANCELLED, NO_SHOW, EXPIRED as terminal states. Draw it as Figure 3.x
     and give the transition table. State that an illegal transition returns 20003 and that
     the legal transitions are expressed as an explicit allowed-transition table in code
     (describe it; do not paste it). NO_SHOW is a distinct terminal state, not a flavour of
     CANCELLED, precisely so the no-show rate in FR-ANA-04 is computable — say why. -->

## 3.6 Requirement-to-use-case coverage

<!-- A table showing every FR ID and the use case(s) that realise it. Any FR with no use
     case is a gap you must flag to M1 before merging — it means a requirement nobody
     modelled, and chapter 12 will not be able to evaluate it. -->

---

## Author's notes — to resolve before merging

- [ ] **Render the Mermaid to images.** The draft may keep Mermaid source (it survives
      review and diffs cleanly), but the final PDF needs exported PNG/SVG. M7 handles export
      at merge time — tell M7 which diagrams you added.
- [ ] §3.4 is the real work here and the part that earns the marks. The diagrams are already
      drawn; **description tables are not**. Budget your time accordingly, and do not spend
      it re-drawing diagrams that already passed review.
- [ ] **The state machine in §3.5 must match the code.** At the time of writing (14 Nov),
      the reservation service on `main` implements only create and cancel — there is no
      explicit allowed-transition table and no `SEATED` / `NO_SHOW` / `EXPIRED` handling.
      Model what was **specified** (that is correct for this chapter, it is a requirements
      chapter), but flag the gap to M2 and to M1 so chapter 6 and chapter 12 do not claim an
      implementation that does not exist.
- [ ] Use-case numbering: pick a scheme (`UC-RES-01`, or plain `UC1` per diagram as
      REQUIREMENTS.md does) and keep it consistent, because chapters 6–10 will refer back.
