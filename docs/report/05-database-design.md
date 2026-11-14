<!--
  AUTHOR: M8 (YUANYUAN XUE)   SUPPORT: M1
  TARGET: 4–5 pages           DUE: 23 Nov 2026
  STATUS: not started
  SOURCES: src/data/schema/, src/data/migration/versions/ (0001 review moderation and
           rating stats, 0002 audit logs, 0003 reservations, 0004 membership auth),
           manual §5.1–5.3 (slot grid, migrations, isolation level, three-layer defence),
           docs/requirements/REQUIREMENTS.md §5 NFR-07
  RULE: no source code. Describe and explain only — ER diagram plus prose and tables.
-->

# 5. Database Design

## 5.1 Platform and storage engine choices

<!-- MySQL 8.0, InnoDB, utf8mb4. Explain WHY each: InnoDB for row-level locking and
     transactions, which the booking guarantee depends on; utf8mb4 because dish names and
     reviews contain Chinese text and utf8mb3 cannot store the full character set. -->

## 5.2 Entity-relationship model

<!-- Figure 5.1 — the ER diagram. Entities: tables, time_slots, reservations, dishes,
     categories, orders, order_items, customers, membership_tiers, points_ledger,
     coupons, coupon_redemptions, reviews, rating_stats, review_moderation, audit_logs,
     users, roles. Show cardinalities and the identifying relationships.
     This is the PHYSICAL view; chapter 4 §4.5 holds the logical/domain view. The two must
     describe the same entities without contradicting each other — coordinate with M1. -->

## 5.3 Table specifications

<!-- One subsection or one table per entity: columns, types, nullability, keys, and the
     reason for any non-obvious choice. Prioritise the tables that carry the concurrency
     guarantee and the ones with interesting constraints:
       - reservations (the unique constraint, the version column, hold_expires_at)
       - points_ledger (append-only, why there is no balance column)
       - reviews (the unique (dish_id, customer_id, order_id) triple, FR-REV-02)
       - order_items (the price snapshot column and why it is not a foreign key lookup,
         FR-ORD-03)
       - audit_logs (append-only, before/after snapshots, redaction of credential-like keys) -->

## 5.4 The slot grid

<!-- Manual §5.1 fixes slot granularity at 30 minutes. Explain how slots are represented
     and how a reservation references (table, slot). This is decided, not open. -->

## 5.5 Concurrency correctness in the schema  ★ the heart of this chapter

<!-- The three-layer defence, and WHY all three layers are needed. This is the strongest
     "Technical Depth" material the project has, and the rubric rewards exactly this kind of
     reasoning:

       Layer 1 — TRANSACTION. The booking critical section runs inside one transaction, so
                 the read-then-write is not interleaved with another request's.
       Layer 2 — OPTIMISTIC LOCKING. A version column is checked at update time; a stale
                 writer fails rather than silently overwriting.
       Layer 3 — UNIQUE CONSTRAINT. The final safety net: the database itself refuses a
                 second active row for the same (table, slot), so even if layers 1 and 2
                 were both bypassed, the invariant holds.

     Explain the failure mode each layer covers that the others do not. Then explain the
     isolation level: NFR-07 requires READ COMMITTED set explicitly per session AND at
     server level rather than relying on MySQL's default REPEATABLE READ — say why the
     project did not simply accept the default.

     Describe how the unique-constraint violation is translated into error code 20001 in the
     frozen envelope. Do NOT paste the code. -->

## 5.6 Seat holds and expiry

<!-- hold_expires_at, the 10-minute hold window (FR-RES-02), and the requirement that
     expiry be correct even when the background job is down — an expired hold must not count
     as occupying the slot (FR-RES-04). Explain how the query that finds free slots treats
     an expired HELD row. This is a subtle correctness argument and worth a full page. -->

## 5.7 Indexing and query performance

<!-- Which indexes exist and which query each serves. NFR-09 requires the dashboard to read
     aggregates rather than raw tables on the hot path — explain the rating_stats /
     aggregate tables that make this possible. -->

## 5.8 Migration strategy

<!-- Alembic, every schema change reversible with a written downgrade, migrations applied
     automatically on container start (NFR-06). Walk the actual migration chain 0001 → 0004
     as the project's schema history. Note that CI runs the real migration chain against a
     real MySQL 8 and fails the build on model/migration drift — that check exists because
     two "model with no migration" defects reached main earlier in the project, which is a
     legitimate engineering lesson to report. -->

## 5.9 Seed data

<!-- The seeded dataset (20 tables, 50 dishes, 100 customers, 500 historical orders,
     200 reviews) is a Wave-1 deliverable you own. The analytics dashboard and the
     recommender CANNOT be demonstrated without it, so state what is seeded, how it is
     generated, and how it is loaded. Chapter 10 and chapter 12 both depend on this. -->

---

## Author's notes — to resolve before merging

- [ ] **§5.5 cannot be written truthfully yet.** As of 14 Nov, on `main`:
      the reservations table (migration 0003) has **no version column and no unique
      constraint** on (table, slot), and the reservation service performs a plain
      read-then-create with no conflict detection at all. The three-layer defence described
      in the manual is therefore **specified but not implemented**. This is the single
      largest technical gap in the project and it is yours plus M2's.
      Options: (a) get it implemented before 23 Nov and write the chapter about the real
      thing — strongly preferred, it is the project's headline claim; or (b) write §5.5 as
      the design and say plainly in chapter 12 that it is not yet demonstrated. **Do not
      write it as though it exists.** M1 has raised this with the group on 14 Nov.
- [ ] Confirm the migration chain in §5.8 against `src/data/migration/versions/` at merge
      time — more migrations will have landed by 23 Nov.
- [ ] §5.9 seed data: verify it is actually loadable, because chapter 12's integration tests
      and chapter 10's recommender evaluation both need it, and both will silently skip or
      fail without it.
- [ ] Coordinate the ER diagram (Figure 5.1) with M1's domain model (Figure 4.4) so the two
      are the physical and logical views of one model.
