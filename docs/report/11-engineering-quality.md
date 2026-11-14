<!--
  AUTHOR: M1 (YAN ZHANG)   SUPPORT: M10, M4
  TARGET: 4 pages          DUE: 4 Dec 2026
  STATUS: not started
  SOURCES: .github/workflows/ci.yml, docs/design/OWASP_TOP10_HARDENING.md,
           docs/design/ARCHITECTURE.md §3 and §6, docs/api/openapi.json,
           src/common/ (config, security, audit, middleware, envelope),
           src/data/migration/versions/, pyproject.toml, CONTRIBUTING.md
  RULE: no source code. Describe the pipeline, the controls and the evidence.
-->

# 11. Engineering Quality

> Objective (h) is a first-class deliverable of this project, not a wrapper around the
> features. This chapter is where the group demonstrates that the software was *engineered*
> — and almost all of the evidence already exists in the repository. Assemble and explain it.

## 11.1 REST API design conventions

<!-- The frozen contract, and why freezing it mattered for a ten-person team:
       - one base path per module (/api/v1/reservations, /orders, /staff, /membership,
         /reviews, /analytics), owned by one person;
       - a single response envelope — code, message, data, request_id, timestamp — so a
         client written against one module works against all of them;
       - five-digit error-code families (0 success; 1xxxx validation; 2xxxx business rule,
         including 20001 slot conflict and 20003 illegal transition; 3xxxx authorisation,
         including 30003 wrong role) — explain the family design, it is what lets a client
         distinguish "your input was wrong" from "the business rule refused" from "you may
         not do this";
       - X-Request-ID appearing in the response header, the application log and any audit row
         the request produced, so one id correlates all three (FR-XX-02);
       - ISO 8601 UTC with a Z suffix;
       - bounded pagination, page_size <= 100, code 10002 above it (NFR-09).
     Then explain the ROUTER REGISTRY: main.py declares module -> (import path, prefix) and
     the loader tolerates a module that does not exist yet, logging and skipping it. Say
     plainly what this bought (ten people could merge in parallel without a shared import
     breaking the app) AND what it cost (a declared-but-missing router fails silently at the
     debug log level, which is why an endpoint can appear in the contract and not be mounted
     — see §11.7). A candid trade-off is worth more marks than a clean story. -->

## 11.2 Continuous integration

<!-- The pipeline in .github/workflows/ci.yml runs on every pull request. Describe each job
     and WHAT IT PROTECTS AGAINST, not just what it runs:
       Repo hygiene      — forbidden files (.env, .pem, secrets/), hardcoded-credential scan,
                           files over 5 MB, empty source files, Conventional Commits subject.
       Lint & types      — formatter, linter, static type checking.
       Security scan     — bandit and pip-audit (NFR-04).
       Unit tests        — pytest with a coverage floor of 80% on src/ (NFR-02).
       Integration &     — a REAL MySQL 8.0 service container; runs the actual Alembic
       concurrency         migration chain, checks for model/migration drift, then runs the
                           integration and concurrency tests.
       Frontend (Vue 3)  — build and type-check the client.
       Docker build      — build the image and smoke-test /health (NFR-06).
       membership-ui     — the membership client's own workflow.
       Aggregate gate    — merges require every required job green; branch ruleset
                           `protect-main` enforces it (NFR-03).
     Mention the concurrency group with cancel-in-progress, which stops a superseded run
     wasting minutes when ten people are opening PRs. -->

### 11.2.1 Two defects the pipeline was changed to catch

<!-- STRONG MATERIAL — real engineering learning, and it is documented in the workflow
     comments themselves:
       1. Model/migration drift. Two separate "ORM model with no migration" defects reached
          main before the integration job was made to run the real migration chain against
          real MySQL and fail on drift. Explain the defect class: a model that exists in code
          but not in the database schema passes every unit test that mocks the DB, and fails
          only in production.
       2. A whole-pipeline INTERNALERROR. An unset pytest-asyncio fixture loop-scope option
          emitted a deprecation warning during pytest_configure; because filterwarnings is
          ["error"], that warning became an error inside the configure hook and produced exit
          code 3, failing unit and integration jobs before a single test ran. The fix set the
          scope explicitly at its source rather than suppressing the warning. Explain why
          fixing the cause beats widening the filter.
     These two stories are the best evidence in the report that the group operated a real
     engineering process. Give them half a page. -->

## 11.3 Security hardening against the OWASP Top 10 (NFR-04)

<!-- The full control-by-control table from docs/design/OWASP_TOP10_HARDENING.md lives HERE,
     not in ch.2 (ch.2 §2.3.1 only summarises and cross-references — agreed with M10).
     For each of the ten categories: the risk, the control implemented, and where the
     evidence is. Controls to cover: parameterised queries only (no string-built SQL);
     bcrypt cost >= 12; secrets from environment only; production refusing placeholder
     secrets and wildcard CORS; /docs disabled in production; rate limiting on review
     submission; non-root container user; bandit and pip-audit in CI. -->

## 11.4 Audit logging (FR-XX-03, NFR-05)

<!-- The audit subsystem in src/common/audit.py and the audit_logs table (migration 0002).
     Append-only rows surviving application restart; before/after snapshots for back-office
     state changes (reservation status, order status, review moderation, points, coupons,
     roles); credential-like keys redacted before storage. Explain WHY redaction happens on
     the write path — an audit log that records a password in order to prove who changed it
     has created a worse problem than the one it solves. -->

## 11.5 Configuration and secrets management

<!-- Environment-only configuration (src/common/config.py); the production profile refuses
     to start with a placeholder JWT secret or a wildcard CORS origin. Explain the fail-fast
     reasoning: a misconfigured production instance that starts successfully is more
     dangerous than one that refuses to boot. -->

## 11.6 Containerisation and deployment (NFR-06)

<!-- Dockerfile and compose: MySQL 8.0 plus the API; migrations applied automatically on
     start; /health as the readiness signal; non-root container user. The CI docker job
     builds the image and smoke-tests it. -->

## 11.7 Known engineering limitations

<!-- Be candid; the rubric rewards honest evaluation and ch.13 builds on this. At the time
     of writing (14 Nov), on main = 14df591:
       - Two routers are declared in the registry but not implemented — `ordering`
         (/api/v1/orders) and `analytics` (/api/v1/analytics). The tolerant loader skips
         them, so the application starts and reports healthy while two contracted endpoint
         groups are absent. This is the cost of the design decision in §11.1 and it should be
         stated here rather than discovered by the examiner.
       - The concurrency test in tests/concurrency/ is not collected by CI (see ch.12 §12.4),
         so the Objective (d) evidence the pipeline was built to produce is not yet produced.
       - The staff service returns hardcoded fixtures rather than querying the database, so
         its endpoints respond successfully without doing work (ch.7).
     Recommend the concrete fix for the first item: make the loader FAIL, or emit a warning
     visible in the CI summary, once every contracted module is expected to exist — the
     workflow comment already says to remove the tolerance when the modules land. -->

---

## Author's notes — to resolve before merging

- [ ] **This chapter is mostly assembly.** The evidence exists: the workflow file, the OWASP
      document, the audit module, four migrations, the pyproject gates. Budget the time for
      *explaining why*, which is what earns the marks, not for describing what.
- [ ] Confirm the coverage figure actually achieved at merge time and cite it (NFR-02 sets
      the floor at 80 %). Pull the number from the CI coverage artifact, do not estimate it.
- [ ] §11.3 must not duplicate ch.2 §2.3.1. M10 has the same instruction; one of you confirm
      with the other before writing.
- [ ] §11.7 will need re-checking on the day of merging — several of these gaps are being
      worked on. Update it against `main` as it stands on 4 Dec, and move anything fixed into
      the body of the chapter.
- [ ] Regenerate `docs/api/openapi.json` from the running app before §11.1 is finalised
      (FR-XX-04 requires this after every route change), so the documented surface matches
      what is mounted.
