<!--
  AUTHOR: M6 (HUANPAI LI)   SUPPORT: —
  TARGET: 4–5 pages         DUE: 4 Dec 2026
  SOURCES: docs/requirements/REQUIREMENTS.md §4.5, seed data spec (manual §5.4),
           ch.5 §5.9 (seed data), src/presentation/api/routers/analytics.py (when it lands)
  STATUS: not started
  RULE: no source code. Metric definitions, formulas, charts and an evaluation table.
-->

# 10. Implementation — Analytics & Recommendation

## 10.1 Dashboard purpose and data sources

<!-- What the manager gets and why. State the architectural rule explicitly: the dashboard
     NEVER writes cross-module SQL — it consumes the aggregate endpoints or database views
     that the ordering and reservation modules provide. This is a dependency-rule consequence
     (ch.4 §4.3.1) and worth stating because it is a design constraint you actually had to
     work within. -->

## 10.2 Metric definitions  ★ define each precisely

<!-- For every metric: the exact definition, the formula, the date-range semantics, and which
     module supplies the underlying data. Precision here is what makes ch.12 able to verify
     the numbers.

       Revenue trend (FR-ANA-01)     — over a selectable date range; state whether it counts
                                       COMPLETED orders only and how cancellations are treated.
       Table turnover (FR-ANA-02)    — seatings per table per day; state the denominator.
       Hourly demand heat map        — day-of-week x hour; state which timestamp defines the
       (FR-ANA-03)                     hour (slot start, not creation time) and why.
       No-show rate (FR-ANA-04)      — NO_SHOW / (NO_SHOW + COMPLETED) over the range. Note
                                       that this formula is only computable because NO_SHOW is
                                       a distinct terminal state (FR-RES-07) — cross-reference
                                       ch.6 §6.6. -->

## 10.3 Visualisation

<!-- The heat map and trend charts, the charting library used, and how aggregates reach the
     client. Include at least one real screenshot populated with the seeded data. -->

## 10.4 The hybrid recommender (FR-ANA-05)  ★ the other showcase

<!-- Manual §8.2 requires the algorithm AND the evaluation results table. Cover:

       1. What is being recommended, to whom, and from what signal (order history).
       2. The two components and how they are combined. The proposal was
          0.7 x item-based collaborative filtering + 0.3 x category-content similarity —
          confirm what the code does and justify the weighting.
       3. Why a hybrid at all: collaborative filtering alone is cold-start-blind for a new
          customer or a new dish; content similarity alone cannot discover cross-category
          affinity. Say what each half fixes.
       4. Pseudocode for the scoring function. No source code. -->

## 10.5 Offline evaluation  ★ required evidence

<!-- Precision@K and MAE, as promised in the proposal and in FR-ANA-05. Present:
       - the dataset: the 500 seeded historical orders (ch.5 §5.9);
       - the train/test split method and why it is not leaking;
       - the value of K and why;
       - a results TABLE with Precision@K and MAE for the hybrid and for each component
         alone, so the hybrid's contribution is visible;
       - an honest reading of the numbers. If the hybrid does not beat its components, say
         so and explain — a candid negative result read with reasoning scores better than an
         unexplained good one, and it is defensible in the viva. -->

## 10.6 Limitations

<!-- Seeded data is not real customer behaviour; a 500-order history is small for
     collaborative filtering; cold start remains. Feed anything you would fix into ch.13. -->

---

## Author's notes — to resolve before merging

- [ ] **The analytics router does not exist yet.** As of 14 Nov, on `main`, the router
      registry declares `/api/v1/analytics` but there is no `routers/analytics.py`, so the
      prefix is not mounted — the loader skips missing modules by design. Your proposal
      deadline for the dashboard layout was 30 Nov and for the recommender 3 Dec, and this
      chapter is due 4 Dec, so the timing is tight but not yet broken. **§10.3's screenshot
      needs real running code**; without it this chapter has no evidence.
- [ ] **The recommender definition was an open question.** `REQUIREMENTS.md` §6 lists the
      hybrid recommender definition as **open** with a 10 Nov deadline and the proposed
      0.7/0.3 weighting. That deadline has passed. Confirm what is implemented, and get the
      agreed definition written back into the contract by PR.
- [ ] §10.5 depends entirely on the seed data existing and being loadable (ch.5 §5.9). M8
      owns it. **Chase it now, not in December** — if the 500 seeded orders are not there you
      cannot produce an evaluation table at all, and FR-ANA-05 becomes unverifiable.
- [ ] The no-show definition was also open (§6 question 9: CONFIRMED not SEATED within
      20 minutes of slot start → staff marks NO_SHOW). Your metric in §10.2 depends on it.
      Confirm with M2 and record the agreed definition.
- [ ] M4 and M6 own the presentation slides and M6 supplies the data figures (manual §8.4).
      Build the charts once here and let the slides reuse the exports.
