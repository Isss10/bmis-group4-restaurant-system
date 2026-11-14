<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: all members
  TARGET: 2–3 pages        DUE: 8 Dec 2026
  STATUS: not started
  SOURCES: every other chapter (this is a synthesis), docs/requirements/REQUIREMENTS.md §6
           (open business rules) and §8 (assumptions and constraints), ch.11 §11.7 and
           ch.12 §12.9 (known limitations)
  RULE: no source code. Prose only.
-->

# 13. Conclusions & Future Work

> **Write this chapter LAST, in December, after ch.12 §12.7 exists.** A conclusion that
> claims more than the evaluation supports is the easiest way to lose credibility across the
> whole report, and the examiner reads these two chapters back to back.

## 13.1 What the project set out to do

<!-- Restate the problem from ch.1 in two or three sentences and list the objectives. Do not
     re-argue them here. -->

## 13.2 What was achieved

<!-- Synthesised from ch.12 §12.7. For each objective, one or two sentences: what was
     delivered and what the evidence is. Be precise about the distinction between
     "specified", "implemented" and "demonstrated by test" — those are three different
     claims and the report loses credibility if it slides between them. -->

## 13.3 What was not achieved, and why

<!-- Equally important, and the rubric rewards candour here. Whatever ch.12 §12.7 marks as
     partially met or not met must be named here with its cause. Known candidates as of
     14 Nov — RE-CHECK against main in December:
       - the concurrency guarantee: specified and defended in design (ch.5 §5.5, ch.6 §6.4),
         but the schema lacks the version column and unique constraint, the service lacks
         conflict detection, and the committed concurrency test is not collected by CI
         (ch.12 §12.4). This is the project's headline claim; its status must be stated
         without softening.
       - the ordering backend: /api/v1/orders is declared in the router registry but not
         mounted (ch.11 §11.7), while the customer-side ordering UI was delivered.
       - the staff backend returning fixtures rather than querying the database (ch.7).
       - the analytics module and recommender evaluation (ch.10).
     For each, say what caused it — parallel delivery across ten people, a decision left open
     past its deadline, an interface frozen before its consumer existed — because a cause is
     what turns a failure into an engineering lesson. -->

## 13.4 What the group learned about the process

<!-- This is genuinely available material and it is unusual in student reports, which makes it
     valuable. Candidates, all documented in the repository or in the group's own notices:
       - Why freezing the API contract, the response envelope and the error-code families in
         week 2 was the single most useful decision the group made, and what it cost.
       - The tolerant router loader: it let ten people merge in parallel, and it also let two
         contracted endpoint groups go missing without failing any check. A decision with both
         a benefit and a price, honestly reported.
       - Two CI incidents that were configuration and process defects rather than code
         defects (ch.12 §12.8), and the checks added so the class cannot recur.
       - The cost of leaving a business rule open past its deadline: the Bayesian m, the
         coupon stacking order, the points earning rate and the recommender weighting were all
         listed as open with October and November deadlines, and each one blocked a chapter. -->

## 13.5 Future work  ★ the rubric explicitly asks for "realistic opportunities"

<!-- Organised, prioritised and argued — not a wishlist. For each item: what it is, why it
     matters, what it would take, and what it depends on. Mandatory entries:

       1. Online payment — excluded from scope by the proposal. Describe what integration
          would require and why it was excluded (a payment gateway brings PCI-DSS obligations
          that are out of proportion to a PoC).
       2. SMS notification — also excluded by the proposal. Same treatment.
       3. Complete the concurrency guarantee in code and make the test enforce it: add the
          version column and the unique constraint, implement conflict detection and the
          state machine, mark the test correctly, raise N to 50 and the repeats to 10, and
          make the CI job fail when a contracted module is missing rather than skipping it.
       4. The six business rules still open in REQUIREMENTS.md §6 — each needs a decision
          written back into the contract before it can be implemented and tested.
       5. Multi-tenancy. REQUIREMENTS.md §8 notes the system is single-tenant and that
          multi-tenancy would change every uniqueness constraint — explain which constraints
          and why, which demonstrates real understanding of the schema.
       6. Walk-in seating, excluded by the fixed-slot-grid assumption.
       7. A real recommender evaluation on real order history rather than seeded data, and
          the cold-start problem for new customers and new dishes (ch.10 §10.6).
       8. Observability in production: structured logging beyond X-Request-ID correlation,
          metrics, and alerting on the hold-expiry job, whose failure mode is silent. -->

## 13.6 Closing assessment

<!-- Two or three sentences on whether the prototype meets its stated purpose as a
     low-cost digital reference solution for a small restaurant, and what a reader should
     take away. Do not introduce anything new here. -->

---

## Author's notes — to resolve before merging

- [ ] **Do not draft this before 6 December.** §13.2 and §13.3 are derived from ch.12 §12.7.
      Writing them earlier means writing them twice.
- [ ] §13.5 items 1 and 2 are **mandatory**: the proposal commits to describing payment and
      SMS as future work, and manual §8.2 repeats the requirement. Omitting them is a direct
      contradiction of a submitted document.
- [ ] Every "not achieved" item in §13.3 must appear in ch.12 §12.7 and, where it is a
      technical gap, in ch.11 §11.7. Cross-check the three lists on the day of merging —
      a limitation mentioned in one chapter and missing from the others reads as an
      inconsistency, which is precisely what the Consistency criterion penalises.
- [ ] Keep to 2–3 pages. This chapter is a synthesis; length here usually means repetition.
- [ ] Get all ten members to read §13.2 before submission. It is the paragraph each of them
      will be asked about in the viva, and nobody should learn what the report claims about
      their module after it is submitted.
