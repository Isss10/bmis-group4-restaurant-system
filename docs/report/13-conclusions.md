<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: all members
  TARGET: 2–3 pages        DUE: 8 Dec 2026
  STATUS: draft v1 (16 Nov) — §13.1/13.4/13.5 written; §13.2/13.3/13.6 PROVISIONAL, must be
          reconciled with ch.12 §12.7 in December (they assert achievement, which only ch.12's
          evaluation can settle). Do NOT treat the provisional sections as final.
  SOURCES: every other chapter (synthesis), docs/requirements/REQUIREMENTS.md §6 (open business
           rules) and §8 (assumptions and constraints), ch.11 §11.7 and ch.12 §12.9, the group's
           own incident notices
  RULE: no source code. Prose only.
-->

# 13. Conclusions & Future Work

> **Provisional draft.** §13.1, §13.4 and §13.5 do not depend on the test evaluation and are
> written to near-final form. §13.2, §13.3 and §13.6 assert what the project achieved, which only
> ch.12 §12.7 can settle; they are drafted against the verified state of `main` at **16 Nov** and
> **must be re-reconciled with ch.12 in December** — a conclusion that claims more than the
> evaluation supports is the fastest way to lose credibility across the whole report, and the
> examiner reads these two chapters back to back.

## 13.1 What the project set out to do

The project set out to replace a paper-and-telephone restaurant workflow that produces booking
conflicts, lost reservation records and order-entry errors, and that leaves the manager with no
queryable data. Its central technical claim is narrow and testable: two customers can never hold
the same table for the same slot, even when they book at the same instant.

The submitted proposal states seven objectives: **(a)** a customer-side module for seat
reservation, menu browsing and order submission; **(b)** a staff backend for reservation and order
management; **(c)** membership & loyalty plus ratings & reviews; **(d)** concurrency-correct
booking through a relational data layer, with functional, integration and concurrency testing;
**(e)** a manager analytics dashboard and a lightweight hybrid recommender evaluated offline;
**(f)** engineering quality — three-tier architecture, documented REST API, automated testing with
coverage, CI on every pull request, OWASP Top 10 hardening, audit logs and Docker deployment —
together with a user manual covering all modules; and **(g)** the proposal, ongoing project updates
and the final presentation. Online payment, SMS notification and commercial cloud services are out
of scope by decision.

## 13.2 What was achieved  *(provisional — reconcile with ch.12 §12.7)*

Engineering quality (objective f) is the strongest area and is substantially delivered: a
three-tier architecture with an enforced dependency rule, a frozen REST contract with a single
response envelope and error vocabulary, a continuous-integration pipeline of eight jobs gating
every pull request behind a branch ruleset with no bypass actors, OWASP hardening at seven of ten
categories fully and two partially, an append-only audit subsystem, four reversible Alembic
migrations proven against a real MySQL 8 in CI, and a containerised deployment that builds and
smoke-tests in CI. Chapter 11 is the evidence.

On the functional side, membership authentication (objective c) is the most complete module — it
ships a service, router, ORM schema, repository, migration, four test files, its own frontend and
CI workflow, and rate-limited login. Ratings and reviews (objective c) deliver order-verified
submission, a moderation queue and Bayesian-average ranking. The staff backend's reservation side
(objective b) is wired to the real reservation service. The manager dashboard and analytics routes
(objective e) are mounted with a frontend component.

🔧 Each of these claims must be checked against ch.12 §12.7 before submission, and stated using the
precise distinction between *specified*, *implemented* and *demonstrated by test* — several items
below are implemented but not demonstrated.

## 13.3 What was not achieved, and why  *(provisional — reconcile with ch.12 §12.7)*

Stated candidly, with a cause for each, because a cause is what turns a shortfall into an
engineering lesson. All items below were verified against `main` at `9258e0a` on 16 Nov and must be
re-checked in December.

- **The concurrency guarantee (objective d) is designed but not demonstrated.** The three-layer
  defence is fully argued in ch.4 §4.6.1 and ch.5, but the shipped `reservations` table has no
  `version` column and no unique constraint, the reservation service has no conflict detection, and
  the committed concurrency test carries no pytest marker so CI never collects it. *Cause:* the
  schema work (M8), the service logic (M2) and the test (M7) sit in three people's lanes with a
  hard dependency order between them, and the database step — the prerequisite for the other two —
  did not land; a web "upload" commit that claimed optimistic locking actually added only two loose
  SQL files outside the migration chain, so the gap was masked by a green pipeline.
- **The ordering backend is not mounted (objective a).** `/api/v1/orders` is declared in the router
  registry but the module file is absent, so the tolerant loader skips it; the customer ordering UI
  was delivered but has no backend to submit to. *Cause:* an interface was frozen and a client built
  before the server existed, and the loader's tolerance — a deliberate parallel-delivery choice —
  let the absence pass without failing any check.
- **The staff order endpoints and the analytics data are placeholders (objectives b, e).** Staff
  order endpoints return empty/`not_found`; the dashboard service returns hardcoded figures and the
  "hybrid recommender" is a sort by rating, with no offline Precision@K / MAE evaluation. *Cause:*
  no seed dataset exists, so there was nothing real to aggregate or evaluate against.
- **Loyalty is not in the running application (objective c).** The points ledger, tiers and coupons
  exist only inside a duplicate upload directory and are not imported by the app; the duplicate's
  migration also collides with the real tree at `0004`. *Cause:* code submitted by web upload rather
  than through a branch, landing in the wrong directory.
- **The user manual covers one module (objective f).** *Cause:* deferred behind code delivery.

## 13.4 What the group learned about the process

This material is genuinely available, documented in the repository and the group's own incident
notices, and unusual in student reports — which makes it worth its space.

- **Freezing the contract early was the most useful decision the group made.** Fixing the response
  envelope, the error-code families and the per-module base paths in week one let ten people write
  clients and servers independently and kept merge conflicts confined to a handful of named shared
  boundaries. The cost was rigidity: changing a frozen value requires a contract-review PR, which
  felt heavy in the moment and proved worth it.
- **A tolerant loader is a decision with both a benefit and a price.** Letting a missing module be
  skipped meant an unimplemented module could never take `/health` down — but it also meant two
  contracted endpoint groups could be absent without failing a single check. The lesson is general:
  a mechanism that fails *soft* must be paired with a check that fails *loud* once the soft path is
  no longer expected.
- **A green pipeline is not the same as working software.** The project hit this repeatedly: empty
  source files passing CI, a missing migration invisible to unit tests that build tables with
  `create_all()`, a deprecation warning crashing the whole suite before any test ran, and — most
  instructively — a concurrency test that is committed, present in the right directory, and never
  collected because it lacks a marker, while the job stays green on other tests. Each time, the fix
  was a check that asserts the *thing that was assumed*, not just the thing that was written.
- **Leaving a business rule open past its deadline has a concrete downstream cost.** The Bayesian
  confidence parameter, the coupon stacking order, the points earning rate and the recommender
  weighting were all flagged open with October/November deadlines; each one later blocked a report
  chapter that could not be written concretely without the value.
- **Submission hygiene is engineering.** Two contributors used the web "upload files" path, which
  produced a mis-committed personal git config, two loose SQL files outside the migration chain, and
  an entire duplicate copy of the project inside the repository. None of these failed CI. The
  remedy is process, not tooling: branch from `main`, edit the real tree, open a pull request.

## 13.5 Future work  ★ the rubric asks for "realistic opportunities"

Prioritised and argued, not a wishlist. Items 1 and 2 are mandatory — the proposal commits to
describing them as future work.

1. **Online payment.** Excluded by the proposal. Integration would require a payment gateway and
   the PCI-DSS obligations that come with handling card data — out of proportion to a
   proof-of-concept, and the reason it was scoped out. A realistic first step is a redirect to a
   hosted checkout that never touches card details on our servers.
2. **SMS notification.** Also excluded by the proposal. It would add a third-party messaging
   dependency and, with it, the only outbound HTTP the system currently has none of — which would
   re-open the SSRF surface that ch.11 records as not applicable. Worth stating precisely because it
   ties a "future feature" to a security consequence.
3. **Complete the concurrency guarantee and make the test enforce it.** Add the `version` column and
   the active-slot unique constraint, implement conflict detection and the seven-state machine, give
   the test its marker, raise N to 50 and the repeats to 10, and make the loader fail (or warn
   CI-visibly) when a contracted module is missing. This is the highest-value item: it converts the
   project's headline claim from designed to demonstrated.
4. **Close the six open business rules** in `REQUIREMENTS.md` §6, writing each agreed value back into
   the contract — they gate implementation and testing for four modules.
5. **Seed data.** A loader for the 20 tables / 50 dishes / 100 customers / 500 orders / 200 reviews
   the design assumes. Without it the dashboard cannot show real numbers and the recommender cannot
   be evaluated; with it, three modules' evidence becomes real at once.
6. **Multi-tenancy.** The system is single-tenant by assumption (`REQUIREMENTS.md` §8). Supporting
   multiple restaurants would change every uniqueness constraint — the active-slot key, the
   review `(dish, user, order)` triple and the points ledger would all need a tenant discriminator —
   which is exactly why it was scoped out and a good demonstration of understanding the schema.
7. **Walk-in seating**, excluded by the fixed 30-minute slot grid; supporting it needs a
   range-overlap model the unique constraint cannot express.
8. **A real recommender evaluation** on real order history rather than seeded data, plus the
   cold-start problem for new customers and dishes (ch.10).
9. **Production observability:** structured logging beyond request-id correlation, metrics, and
   alerting on the hold-expiry job — whose failure mode is silent by design (correctness does not
   depend on it, so nothing notices when it dies).

## 13.6 Closing assessment  *(provisional — reconcile with ch.12)*

As a proof of concept the system demonstrates its engineering-quality objectives convincingly and
its core domain claim only partially: the architecture, contract, CI discipline and security
hardening are real and verifiable, while the concurrency guarantee that motivates the whole project
is designed and argued but not yet demonstrated in running code. Whether the prototype meets its
stated purpose as a low-cost digital reference for a small restaurant therefore depends on closing
the objective (d) gap before submission; this assessment must be re-stated against ch.12 §12.7 in
December.

---

## Author's notes — to resolve before merging

- [ ] **§13.2, §13.3 and §13.6 are provisional.** They are drafted against `main` at `9258e0a`
      (16 Nov) and **must be rewritten from ch.12 §12.7 in December.** Do not merge them as final.
      §13.1, §13.4 and §13.5 are not evaluation-dependent and are close to done.
- [ ] §13.5 items 1 and 2 are **mandatory** (the proposal commits to payment and SMS as future
      work; manual §8.2 repeats it). Keep them.
- [ ] **Three-way cross-check on merge day:** every "not achieved" item in §13.3 must also appear in
      ch.12 §12.7 and, where technical, in ch.11 §11.7. A limitation in one chapter and missing from
      the others reads as inconsistency — exactly what the Consistency criterion penalises.
- [ ] Keep to 2–3 pages. §13.4 is the section most likely to overrun; it is the most original
      material but must stay tight.
- [ ] **All ten members read §13.2/§13.3 before submission.** It is what each will be asked about in
      the viva; nobody should learn what the report claims about their module after it is submitted.
