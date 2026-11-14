# Technical Report — Working Directory

**JC2001 BMIS Group 4 — Restaurant Reservation and Food-Ordering System**

This directory holds the section drafts of the final technical report. One file per
chapter, one named author per chapter. The final deliverable is a **single PDF of 40–60
pages** (Introduction → Conclusions count towards the page total; cover page, table of
contents, list of figures/tables, references and Appendix A do not).

> **Why this directory exists.** The report carries **50 % of the project mark** — more
> than the software (30 %) and the presentation (20 %) combined. The manual (§8.2)
> scheduled this skeleton for **5 October**; it did not exist until now. Every chapter has
> a named author and a delivery date, and drafts are meant to land in the same week the
> code does, so that December is spent on merging, formatting and consistency checking
> rather than on writing from a blank page.

---

## 1. How to use this directory

1. Find your chapter in the table below. **You are the author.** Do not edit someone
   else's chapter without telling them — merge conflicts across ten people are the main
   thing this structure exists to prevent.
2. Write directly in your file. Keep the front-matter block at the top up to date
   (`status`, `pages`).
3. Commit with a Conventional Commits subject, e.g.
   `docs(report): draft chapter 9 Bayesian ranking (M9)`.
4. Open a pull request against `main`. CI must be green before merging; `docs(report)`
   changes do not affect the code jobs, so your PR should pass trivially.
5. **Do not paste source code.** The school brief is explicit: *"Do not include source
   code in the technical report; instead, describe and explain only the relevant
   implementation details, algorithms, and software structure."* Use prose, pseudocode,
   flowcharts, class diagrams and sequence diagrams instead. A chapter that fails this
   rule loses marks for the whole group.

### Formatting requirements (apply to the final PDF)

A4 · 2.54 cm (1 inch) margins on all four sides · single column · 12 pt ·
Arial or Times New Roman · 1.5 line spacing.

These are checked by the examiner. Non-compliant formatting is free marks thrown away, so
the merging step (§4 below) re-applies them to the whole document at once — individual
authors should write in Markdown and not fight with layout now.

### Figures and tables

- Number them per chapter: `Figure 4.1`, `Table 4.2`. The final list of figures is
  generated from these numbers, so do not use ad-hoc numbering.
- Prefer Mermaid source in the draft (it is diff-able and survives review); the merger
  exports each diagram to PNG/SVG for the PDF.
- Every diagram referenced by the marking rubric must actually appear. Chapter 4 in
  particular is expected to contain **five** kinds of model — see its checklist.

---

## 2. Chapter ownership and schedule

Status legend: ⬜ not started · 🟨 drafted · 🟩 reviewed · ✅ merged into the final PDF.

| # | Chapter | Author | Support | Target pages | Due | Status |
|---|---|---|---|---|---|---|
| 1 | Introduction & Project Context | **M1** | all | 4–5 | 16 Nov | 🟨 |
| 2 | Functional & Non-Functional Requirements | M10 | M1 | 5–6 | 16 Nov | ⬜ |
| 3 | Use Cases & Requirements Modelling | M3 | M2, M5 | 6–7 | 20 Nov | ⬜ |
| 4 | System Design & Architecture | **M1** | M8 | 8–9 | 23 Nov | ⬜ |
| 5 | Database Design | M8 | M1 | 4–5 | 23 Nov | ⬜ |
| 6 | Implementation — Reservation & Ordering | M2 | M5 | 4–5 | 27 Nov | ⬜ |
| 7 | Implementation — Staff Backend | M3 | — | 3 | 27 Nov | ⬜ |
| 8 | Implementation — Membership & Loyalty | M10 | M4 | 4 | 27 Nov | ⬜ |
| 9 | Implementation — Ratings & Reviews | M9 | — | 3–4 | 27 Nov | ⬜ |
| 10 | Implementation — Analytics & Recommendation | M6 | — | 4–5 | 4 Dec | ⬜ |
| 11 | Engineering Quality | **M1** | M10, M4 | 4 | 4 Dec | ⬜ |
| 12 | Testing & Evaluation | M7 | M4 | 6–7 | 6 Dec | ⬜ |
| 13 | Conclusions & Future Work | **M1** | all | 2–3 | 8 Dec | ⬜ |
| — | References | **M1** | each author reports own | not counted | 8 Dec | ⬜ |
| — | Appendix A — Group Workload Profile | **M1** | all sign | not counted | 10 Dec | ⬜ |
| — | Front matter (cover, contents, list of figures/tables) | M7 | M1 | not counted | 10 Dec | ⬜ |

Page budget: chapters 1–13 total **55–70 pages of draft**. Trim to the 40–60 window during
merging — overshooting is a much cheaper problem to have than undershooting, so do not
self-censor now.

---

## 3. Source material already in the repository

Much of the report can be assembled rather than invented. Existing documents:

| Existing file | Feeds chapter |
|---|---|
| `docs/requirements/REQUIREMENTS.md` | 2, 3, 12 — FR/NFR IDs are stable, cite them by ID |
| `docs/design/ARCHITECTURE.md` | 4, 11 — three-tier rationale, dependency rule, §13 open questions |
| `docs/design/OWASP_TOP10_HARDENING.md` | 11 — the OWASP mapping table goes in almost verbatim |
| `docs/design/MEMBERSHIP_MEMBER10.md` | 8 |
| `docs/api/openapi.json` | 11 — summarise the surface; do not print the JSON |
| `docs/api/MEMBERSHIP_AUTH.md` | 8, 11 |
| `docs/testing/RESERVATION_MEMBER7_ACCEPTANCE.md` | 12 |
| `docs/user-manual/` | PoC ZIP deliverable, not the report |
| `.github/workflows/ci.yml` | 11 — describe the pipeline; the job list is the evidence |
| `src/data/migration/versions/` | 5 — migration history shows schema evolution |
| The group proposal (submitted, `pdf/20260924/proposal-update/`) | 1 — Problem / Solution / Benefits / Objectives |

**Traceability is a marked criterion.** The rubric rewards *Consistency and Technical
Depth*: problem → requirements → modelling → design → implementation → testing must line
up. `REQUIREMENTS.md` §7 already carries the objective-to-requirement-to-test matrix; every
chapter should cite the `FR-*` / `NFR-*` / `Objective (x)` IDs it covers so that chain stays
auditable.

---

## 4. Merging procedure (8–10 December, M1 + M7)

1. Merge all chapter files into one document in numeric order.
2. Unify terminology and figure/table numbering across chapters.
3. Unify the citation style — **pick one of IEEE or Harvard and apply it everywhere**.
   Mixed styles are an obvious deduction.
4. Run the six-way consistency check: problem / requirements / modelling / design /
   implementation / testing.
5. Apply the formatting requirements listed in §1.
6. Generate the table of contents and the list of figures and tables.
7. Count the pages (40–60, counting Introduction → Conclusions only).
8. Export a single PDF and cross-check it against the presentation and the PoC — the three
   must describe the same system. **Do not claim a feature the software does not have.**

---

## 5. Standing constraints

- **Feature freeze after 1 December.** Anything someone still wants to build goes into
  chapter 13's Future Work instead. The rubric explicitly asks for *"realistic opportunities
  for further development"*, so a well-argued Future Work section scores marks.
- Online payment and SMS notification are **out of scope permanently** (proposal) and must
  be described as future work, never as missing functionality.
- All content passes Turnitin. AI-tool use must follow the school's guidance, and any
  external material must be cited. An uncited source is an academic-misconduct risk, not a
  formatting nit.
