<!--
  AUTHOR: M10 (RONG CONG)   SUPPORT: M1
  TARGET: 5–6 pages         DUE: 16 Nov 2026
  STATUS: not started
  SOURCES: docs/requirements/REQUIREMENTS.md §4–5 (FR/NFR tables),
           docs/design/OWASP_TOP10_HARDENING.md, manual §4.4 role matrix, §4.5 enums
  RULE: no source code. Describe and explain only.
-->

# 2. Functional & Non-Functional Requirements

## 2.1 Requirements elicitation and method

<!-- How were the requirements derived? Name the sources: the group proposal (the
     commitment made to the school), discussion with the supervisor, and the internal
     contract handbook. Explain the ID scheme FR-<MOD>-<nn> / NFR-<nn> and state that IDs
     are stable and cited by the tests and by the workload profile — that stability is what
     makes the traceability in §2.4 auditable. -->

## 2.2 Functional requirements

<!-- Reproduce the five module tables from REQUIREMENTS.md §4, grouped as:
       2.2.1 Reservation (FR-RES-01 … 08)
       2.2.2 Ordering (FR-ORD-01 … 05)
       2.2.3 Membership & Loyalty (FR-MEM-01 … 06)
       2.2.4 Ratings & Reviews (FR-REV-01 … 05)
       2.2.5 Analytics (FR-ANA-01 … 05)
       2.2.6 Cross-cutting (FR-XX-01 … 04)
     Keep the ID / requirement / priority columns. Do NOT invent new requirements here that
     no module implements — every FR must be either built or explicitly deferred to ch.13. -->

## 2.3 Non-functional requirements

<!-- NFR-01 … NFR-09 from REQUIREMENTS.md §5, each with its verification method. This table
     is what chapter 12 is graded against, so the "Verification" column must name a real
     artefact that exists (a test path, a CI job, a document). -->

### 2.3.1 Security requirements (OWASP Top 10)

<!-- The OWASP mapping table from docs/design/OWASP_TOP10_HARDENING.md belongs here, or is
     summarised here and given in full in chapter 11 — pick ONE home and cross-reference, do
     not print the same table twice. M1's recommendation: summarise here (one paragraph per
     category, stating the requirement), give the full control-by-control table in ch.11
     where the implementation evidence lives. -->

### 2.3.2 Performance, reliability and data requirements

<!-- NFR-07 (MySQL 8 InnoDB, utf8mb4, explicit READ COMMITTED, reversible Alembic
     migrations) and NFR-09 (pagination bounded at page_size <= 100). -->

## 2.4 Role-permission matrix

<!-- The frozen matrix from manual §4.4: four roles x the endpoint groups. State explicitly
     that a valid token with the wrong role yields 30003 and never a 401-as-403 confusion
     (FR-MEM-02). This table is referenced by chapters 3, 7 and 8 — number it Table 2.x and
     cross-reference rather than repeating it. -->

## 2.5 Traceability

<!-- Reproduce REQUIREMENTS.md §7: objective -> requirements -> test evidence -> owner.
     This is the single most valuable table in the report for the "Consistency" criterion,
     because it links the proposal's promises to the tests that prove them. -->

## 2.6 Requirement changes during the project

<!-- Any requirement added, dropped or re-prioritised after the proposal, with the reason.
     Honest scope changes read as engineering judgement; silently missing requirements read
     as failure. Anything dropped must also appear in ch.13 Future Work. -->

---

## Author's notes — to resolve before merging

- [ ] **Agree with M1 where the OWASP table lives** (see §2.3.1) before either of you
      writes it, or it will be printed twice and one copy will go stale.
- [ ] **Objective lettering.** The proposal uses (a)–(i); the manual and REQUIREMENTS.md use
      (a)–(g). Chapter 1 flags this too. Settle it once, group-wide, and use the same
      lettering here.
- [ ] Six of the nine "open business rules" in REQUIREMENTS.md §6 (max table occupation,
      points earning rate and expiry, coupon stacking order, Bayesian `m`, recommender
      definition, no-show definition) were listed as **awaiting a group decision** with
      deadlines of 20 Oct / 10 Nov. Several directly affect requirements in your chapter
      (FR-MEM-04, FR-MEM-05, FR-ANA-04, FR-ANA-05). **Check whether each was ever decided**,
      and if so record the agreed value here as a requirement; if it was not, say so and make
      sure ch.13 lists it. A requirement whose value is undefined cannot be tested, and
      chapter 12 will not be able to close the loop.
- [ ] Every NFR must name a verification artefact that **actually exists at merge time**.
      NFR-01 currently points at `tests/concurrency/` — M1 has found that the concurrency
      test there is not collected by CI (see the group thread of 14 Nov). Do not write
      "verified by the concurrency test" until that is fixed, or chapter 12 contradicts you.
