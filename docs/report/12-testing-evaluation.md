<!--
  AUTHOR: M7 (JIAYI TAN)   SUPPORT: M4
  TARGET: 6–7 pages        DUE: 6 Dec 2026
  SOURCES: tests/unit/, tests/integration/, tests/concurrency/, pyproject.toml (pytest
           config, markers, coverage floor), .github/workflows/ci.yml (test-integration job),
           docs/testing/, docs/requirements/REQUIREMENTS.md §5 (NFR-01, NFR-02) and §7
           (traceability matrix)
  STATUS: not started
  RULE: no source code. Test-case tables, result tables, charts and prose.
-->

# 12. Testing & Evaluation

> This chapter carries Objective (c) and the evidence for NFR-01 and NFR-02, and it is the
> chapter the examiner reads to decide whether the group's central claim is true. **It is
> also, as of 14 November, the chapter with the largest gap between what the repository
> appears to show and what it actually proves.** Read §12.4's author note before writing
> anything.

## 12.1 Test strategy

<!-- The three levels and what each is for:
       unit          — fast, isolated, no external dependency; services called directly
                       without HTTP, which the three-tier split makes possible (ch.4 §4.1);
       integration   — the full application against a REAL MySQL 8.0 service container, with
                       the real Alembic migration chain applied first;
       concurrency   — N simultaneous requests racing for one resource, asserting the
                       invariant on both the HTTP responses AND the database row count.
     Explain why concurrency correctness cannot be tested at unit level with a mocked
     database: a mock has no transactions, no row locks and no unique constraints, so it
     cannot reproduce the interleaving the guarantee is about. This is the reasoning behind
     the CI job's real MySQL service, and it is worth stating explicitly. -->

## 12.2 Unit tests

<!-- Inventory: which modules are covered, how many tests, what the coverage figure is.
     Pull the number from the CI coverage artifact — do not estimate it. NFR-02 sets the
     floor at 80% of src/, enforced by the unit job's --cov-fail-under.
     Present a table: module -> test file -> what it verifies -> pass/fail. -->

## 12.3 Integration tests

<!-- The smoke test and the MySQL-backed membership tests. Explain what the smoke test
     proves (the app assembles, migrations apply, /health responds) versus what the
     module integration tests prove. Include the model/migration drift check as part of the
     integration story — it is a test of the schema, not just of the code. -->

## 12.4 Concurrency testing (NFR-01, Objective d)  ★ the centrepiece

<!-- What NFR-01 actually requires, verbatim from the requirements specification:
       with N >= 50 simultaneous booking requests for one table and slot, exactly one
       succeeds (code 0) and the rest receive 20001; the database afterwards holds exactly
       one active row; repeatable 10x with identical results.
     Present: the test design, the invariant asserted, the results table across the repeats,
     the distribution of outcomes, and the database row count. Manual §8.2 requires a test
     report with a timestamp, the successful request id and the failure distribution, and
     the presentation shows 50 concurrent requests producing 1 code:0 and 49 code:20001. -->

## 12.5 Coverage

<!-- The achieved figure per module against the 80% floor, from the CI artifacts. Explain
     what coverage does and does not tell you — high coverage with no concurrency test still
     leaves the central claim unproven, which is a candid and defensible observation. -->

## 12.6 Security testing

<!-- bandit and pip-audit results from the CI security job (NFR-04). Report findings and
     their disposition. -->

## 12.7 Evaluation against the objectives  ★ required by the rubric

<!-- A table, objective by objective, stating for each: what was required, what was
     delivered, the evidence, and a verdict of met / partially met / not met. This is the
     single most important table in the chapter. Be honest — a candid "partially met, and
     here is what remains" is defensible in a viva; an unqualified claim that ch.11 or the
     software contradicts is not, and it puts the whole report's credibility at risk.
     Use the proposal's objective lettering (see the note below). -->

## 12.8 Defects found and fixed

<!-- The bug record. Two candidates are already documented in the CI workflow comments and
     make excellent material because they are process defects rather than typos:
       - two "ORM model with no migration" defects reaching main, and the drift check added
         in response;
       - the pytest-asyncio configuration error that produced an INTERNALERROR and failed the
         whole pipeline before any test ran (a full write-up exists in the group's 4 Nov
         incident notice).
     For each: symptom, root cause, fix, and what was changed so the class of defect cannot
     recur. The last part is what distinguishes engineering from debugging. -->

## 12.9 Limitations of the testing

<!-- What the test suite does not cover, stated plainly. Include anything that was specified
     but not verified, and cross-reference ch.13. -->

---

## Author's notes — CRITICAL, read before writing

- [ ] **The concurrency test has never executed.** M1 verified this on 14 Nov against
      `main` = `14df591`. The chain of facts:

      1. `tests/concurrency/test_concurrent_booking.py` declares only
         `pytestmark = pytest.mark.skipif(not os.getenv("APP_DB_HOST"), ...)`. It carries
         **neither** the `concurrency` **nor** the `integration` marker.
      2. The CI job runs
         `pytest tests/integration tests/concurrency -m "integration or concurrency" ...`.
         The `-m` expression therefore **deselects** the whole file. It is not skipped — it
         is never collected.
      3. Contrast `tests/integration/test_membership_mysql.py`, which does declare
         `pytestmark = pytest.mark.integration` plus three `@pytest.mark.concurrency` tests.
         Those run. The booking test does not.
      4. Because the membership tests ARE collected, the job does not exit with code 5, so
         the pipeline's own notice — *"No integration or concurrency tests collected yet…
         Objective (d) requires the automated concurrent-booking test before 30 Nov 2026"* —
         never prints. **The green "Integration & concurrency tests" check is therefore not
         evidence for Objective (d).** It is green because the membership tests pass.

      **Do not write §12.4 as though the guarantee is demonstrated.** It is not, and
      ch.11 §11.7 already says so.

- [ ] **The test would also fail if it ran.** Five separate defects, all verified on 14 Nov:

      | # | Defect | Reality on `main` |
      |---|---|---|
      | 1 | POSTs to `/api/v1/reservations/book` | No such route. The registry mounts the router at `/api/v1/reservations` and the handler is `@router.post("")`, so the real endpoint is `POST /api/v1/reservations`. |
      | 2 | Sends `slot_date`, `slot_start`, `party_size` | `ReservationCreateSchema` accepts `table_id`, `reservation_time` (a datetime) and an optional `user_id`. The payload would be rejected 422. |
      | 3 | Sends no credentials | The handler depends on `require_roles(Role.CUSTOMER)`, so an unauthenticated request is refused before any booking logic runs. |
      | 4 | Asserts on HTTP status codes (200/201 win, 400/409 conflict) | The frozen contract expresses outcomes as envelope **codes** — `code:0` for success and `20001` for a slot conflict (manual §5.4). Asserting transport status cannot observe the business code, so the test would not detect the behaviour it exists to prove. |
      | 5 | `_assert_one_row_in_db` queries `reservations.slot_date` / `.slot_start` | There is no ORM model for reservations (`src/data/schema/` holds only `membership.py` and `review.py`), and the test's own comment says "Filled in once ORM model lands". |

      Underneath all five: the reservation service performs a plain read-then-create with **no
      conflict detection**, and the reservations table has **no version column and no unique
      constraint**. There is currently nothing that could make a second concurrent booking
      fail — so even a correctly written test would observe 10 successes, not 1.

- [ ] **The scale does not meet NFR-01 either.** The test uses `N_WORKERS = 10` and
      `REPEATS = 5`. NFR-01 requires **N ≥ 50** and **repeatable 10×**. Fix the constants when
      the test is repaired, or §12.4 cannot claim NFR-01 is satisfied.

- [ ] **What §12.7 must therefore say about Objective (d):** not met as of 14 Nov. The
      requirement is specified, the CI infrastructure to prove it exists and works (the real
      MySQL service, the migration chain, the marker registration in `pyproject.toml`), and a
      test file is committed — but the test is not collected, does not match the API, and the
      behaviour it targets is not implemented. The proposal's own deadline for this was
      30 Nov. **Escalate to M1 and M2 immediately**; this is the project's headline technical
      claim and it is also the centrepiece of the presentation (manual §8.4).

- [ ] **Objective lettering.** The proposal uses (a)–(i); the internal manual and
      `REQUIREMENTS.md` §7 use (a)–(g), where the manual's (d) is "concurrency correctness +
      testing" but the proposal's (c) is the testing objective and its (d) is the user manual.
      §12.7 must use ONE lettering — ch.1 §1.6 flags the same issue. Settle it group-wide
      before anyone writes an objective table, or the report will contradict itself in the
      exact place the "Consistency" criterion examines.

- [ ] You also own the front matter (cover, contents, list of figures/tables) and the
      **8–12 page user manual** for the PoC ZIP. `docs/user-manual/` currently holds only
      `MEMBERSHIP_AUTH.md` and a `README.md`. PR #11 brought in
      `docs/testing/RESERVATION_MEMBER7_ACCEPTANCE.md` and `docs/user-manual/README.md` —
      reuse that material rather than starting cold.
