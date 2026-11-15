<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: every chapter author reports their own sources
  TARGET: not counted in the 40–60 page total   DUE: 8 Dec 2026
  STATUS: not started
-->

# References

## Citation style — DECIDE ONCE, APPLY EVERYWHERE

**Chosen style: ⬜ IEEE  ⬜ Harvard**  *(pick one before any author cites anything)*

The whole report must use a single style. Mixed citation styles are immediately visible to an
examiner and are an avoidable deduction. Whichever is chosen, apply it to in-text citations
and to this list consistently, and number or order the entries the same way throughout.

> **Note on page count:** references are **not** counted towards the 40–60 page total
> (manual §8.1). Neither are the cover page, table of contents, list of figures and tables,
> or Appendix A. Only Introduction → Conclusions counts.

## How to contribute an entry

Each chapter author adds their own sources to the relevant section below, **in the chosen
style**, and tells M1 in the pull-request description. M1 de-duplicates and renumbers at
merge time — so do not worry about ordering, but do include every field the style requires.

---

## Standards and specifications

<!-- e.g. the OWASP Top 10 (cite the specific version used by docs/design/
     OWASP_TOP10_HARDENING.md), the HTTP specification for the status codes and methods used,
     ISO 8601 for the timestamp format, JSON Web Token (RFC 7519) for the authentication
     scheme. Cite the VERSION and the access date for anything read online. -->

## Technology documentation

<!-- FastAPI, Vue 3, Vite, TypeScript, SQLAlchemy 2.0, Alembic, pytest, pytest-asyncio,
     MySQL 8.0 reference manual (especially the sections on InnoDB locking and transaction
     isolation levels, which ch.5 relies on), Docker. Cite the version the project pins in
     pyproject.toml / package.json, not "latest". -->

## Academic and background sources

<!-- Anything cited in ch.1 §1.1 to support the problem statement — restaurant digitalisation,
     booking-conflict costs, concurrency control in transactional databases. The Bayesian
     average in ch.9 §9.3 needs a proper source for the formula. The collaborative-filtering
     and content-based recommendation approaches in ch.10 §10.4 need sources, as do the
     Precision@K and MAE metrics. -->

### Candidate entries collected 14 Nov 2026 (M1) — verify each before citing

The following were located while drafting ch.1 and ch.9. **They are candidates, not approved
entries.** Each still needs: full bibliographic details retrieved from the publisher page,
formatting in the chosen style, and a check that the source actually says what the citing
sentence claims. Do not cite from this list without opening the source.

Cited in the current ch.1 draft as [1]–[3]:

| Ref | Candidate source | Supports | Caution |
|---|---|---|---|
| [1] | *AI Agent for Automated Restaurant Table Reservations Using n8n*, IEEE Xplore, 2026, doc. 11559338 | ch.1 §1.1 — phone/manual registers are error-prone at peak hours and produce double bookings | IEEE abstract page; confirm the claim is in the abstract or full text, not inferred from the title |
| [2] | *Project Management in Prototyping an Online Table Reservation System*, International Journal of Information Systems and Engineering (e-journal.uac.ac.id), 2026, article 9314 | ch.1 §1.1 — most restaurants still rely on manual reservation, leading to miscommunication and double bookings | Lower-tier venue; acceptable as supporting evidence alongside [1], not as the sole source |
| [3] | *A Web-Based Innovative Approach of the Booking System for the Food Industry*, IEEE Xplore, 2025, doc. 11273655 | ch.1 §1.1 — digitising reservations reduced manual errors such as double bookings | As [1] |

For ch.9 §9.3 (Bayesian average) — **the formula must be attributed**:

| Candidate source | Use |
|---|---|
| Wikipedia, *Bayesian average* | Definitional source for the estimator. Acceptable for a formula that is standard, but prefer a textbook or the original paper if one is found |
| IMDb Help, *Weighted Average Ratings* | The best-known production deployment of this exact estimator; WR = (v/(v+m))·R + (m/(v+m))·C. Strong practical precedent to cite alongside the formula, and it justifies the choice of a prior mean plus a confidence weight |
| E. Miller, *Bayesian Average Ratings*, evanmiller.org, 2012 | Discusses the caution parameter explicitly — useful for defending the choice of m in §9.3(4) |
| T. Fahrudin, *New custom rating for improving recommendation system*, Journal of Big Data, 2024, doi 10.1186/s40537-024-00952-3 | Peer-reviewed and recent; preferable to a blog if it covers the same ground — check whether it does before substituting |

For ch.10 §10.4 (hybrid recommender, Precision@K, MAE) — **no source has been located yet.**
This is a gap. Standard references are needed for item-based collaborative filtering, for
content-based similarity, for hybridisation, and for the Precision@K and MAE metrics. Assign
to M6.

⚠️ **Do not use this figure without a second source.** A no-show rate of 2.33 %, measured
across roughly 3.77 million reservations at 2,417 restaurants, appears in the *Resos No-Show
Index 2026* (resos.com) and is repeated by restaurantbookingsystem.com — but both trace to the
same index, so it is **single-source**. It would be a useful number for ch.1 §1.1 and for
justifying FR-ANA-04. Either find an independent measurement, or cite it explicitly as the
Resos index's own figure with that attribution visible, or leave it out. Note that the vendor
publishing the index sells reservation software, which is a reason to attribute rather than
assert. Academic alternatives exist and are better: *Modeling no-shows, cancellations,
overbooking, and walk-ins in restaurant revenue management*, Journal of Foodservice Business
Research, 2017, doi 10.1080/15378020.2016.1198626; and *Are reservations recommended?*,
M&SOM, 2012, doi 10.1287/msom.1110.0360.

## Course and project materials

<!-- The group's own submitted proposal; the school's project brief and marking criteria.
     Cite these too — they are the documents the requirements trace back to, and the
     traceability claim in ch.2 §2.5 depends on them being identifiable. -->

---

## Author's notes — to resolve before merging

- [ ] **No chapter currently cites anything.** The drafts in this directory were written from
      the group's own committed documents, which is fine for internal material, but ch.1
      §1.1 asserts claims about restaurant operations without a source, ch.9 §9.3 uses a
      formula that needs attribution, and ch.10 §10.4 uses named techniques and metrics that
      must be cited. **Every one of those needs a real reference.**
- [ ] **All content passes Turnitin.** Uncited external material is an academic-misconduct
      risk, not a formatting issue. AI-tool use must follow the school's guidance — check what
      that guidance requires (some institutions require a declaration of AI use) and include
      the declaration if so.
- [ ] De-duplicate at merge: several chapters will cite the OWASP Top 10, the MySQL reference
      manual and FastAPI independently. One entry each, cited from multiple places.
- [ ] Verify every URL resolves and every access date is the date you actually read it, on the
      day of merging. A dead link in a references list is a visible defect.
