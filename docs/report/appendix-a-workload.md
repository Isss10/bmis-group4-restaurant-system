<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: all ten members must sign
  TARGET: not counted in the 40–60 page total   DUE: 10 Dec 2026
  STATUS: not started
  SOURCE: the school's own workload-profile template. A filled version already exists in the
          group's working folder as "Group workload profile（已填写）.docx".
-->

# Appendix A — Group Workload Profile

> **Use the school's template, not a homemade table.** This appendix is a required submission
> item in its own right and must be **signed by all ten members**. It is not counted towards
> the report's 40–60 page total.

## What goes here

The school's workload-profile form, completed and signed. A filled copy already exists in the
group's working folder (`Group workload profile（已填写）.docx`) — **verify it against what was
actually delivered** before submitting, because it was filled in earlier in the project and
the work has moved on since.

## Member roster

| Member | Name | Student ID | Primary ownership |
|---|---|---|---|
| Member1 | YAN ZHANG | 50106059 | Engineering quality, CI, contract; report ch. 1, 4, 11, 13 |
| Member2 | KEYING CHEN | 50106003 | Reservation backend; report ch. 6 |
| Member3 | RANXI HE | 50106057 | Staff backend UI; report ch. 3, 7 |
| Member4 | GEMAN MENG | 50106067 | Coupons, loyalty, presentation; report ch. 8 support |
| Member5 | ZIHAN ZHU | 50106018 | Ordering, customer frontend; report ch. 6 support |
| Member6 | HUANPAI LI | 50106069 | Analytics dashboard, recommender; report ch. 10 |
| Member7 | JIAYI TAN | 50106009 | Testing, CI concurrency, user manual, video; report ch. 12 |
| Member8 | YUANYUAN XUE | 50106048 | Database schema, seed data; report ch. 5 |
| Member9 | RUNYI PENG | 50106030 | Ratings and reviews, Bayesian ranking; report ch. 9 |
| Member10 | RONG CONG | 50106064 | Membership and authentication; report ch. 2, 8 |

## Contribution evidence

<!-- The appendix is stronger if the claimed contribution can be corroborated. For each
     member, the git authorship on main is the objective record. Generate it at merge time:

       git shortlog -sne origin/main          # commits per author
       git log --format='%aN' | sort -u       # distinct authors

     Include the summary table here. If a member's contribution is mostly in a branch that was
     squashed on merge, note that — squash merging hides individual authorship in the commit
     list, and an examiner comparing the appendix against the git log should not find a
     mismatch it cannot explain. -->

---

## Author's notes — to resolve before merging

- [ ] **Confirm the squash-merge effect.** If PRs were squash-merged, `git shortlog` on `main`
      attributes each change to whoever merged it, not to the author. Check whether the
      authorship record still supports the workload claims; if not, gather the evidence from
      the PR list instead and say how it was derived.
- [ ] All ten signatures are required. **Chase them in the first week of December**, not on
      10 December — a missing signature on a mandatory submission item is an avoidable
      administrative failure.
- [ ] Verify the existing `.docx` against the delivered work. It was completed earlier in the
      project; chapters, modules and owners have shifted since.
- [ ] Cross-check this roster against ch.1 §1.5 and against the chapter ownership table in
      `README.md`. Three places list who did what; if they disagree, the examiner notices.
