# Member10 — 23 November authentication and permissions delivery

Prepared: 8 November 2026. Task: **T4 Membership & Loyalty**. Member10 owns
FR-MEM-01, FR-MEM-02 and the role-management portion of FR-MEM-06, as assigned in
[the merged requirements](../requirements/REQUIREMENTS.md). Member4 owns points,
tiers and coupons (FR-MEM-03/04/05). Implementation is submitted in
[PR #10](https://github.com/Isss10/bmis-group4-restaurant-system/pull/10).

## Leader's migration review

The branch is rebased on main `963c70e`. Membership migration is now
`0004_add_membership_auth.py`, revision `0004`, down_revision `0003`.
Main's 0001 review, 0002 audit and 0003 reservation migrations are preserved.
Membership no longer duplicates audit-table creation. There is a single head.
Tests check a fresh database, an existing main database with audit/reservation
data, upgrade to 0004, rollback to 0003 without losing that data, and re-upgrade.
A complete rollback to base follows main's original destructive downgrades.

## Completed Member10 behaviour

- Customer-only registration, four-role login and caller-only identity/profile.
- In-memory access tokens, secure refresh-cookie handling, CSRF, refresh rotation,
  replay revocation, logout and live session/role/status checks.
- Admin account creation/listing, role/status changes, stale-version handling,
  last-active-admin protection and audit in the same transaction.
- Unified main envelope and frozen error codes across the auth API and Vue client;
  generated OpenAPI includes the current mounted routes.
- Mounted reservation and review writes enforce customer role and verified
  identity. Cancelling another customer's reservation is refused under a row
  lock before any mutation. All four mounted staff operations validate sessions.
- Frontend, first-admin bootstrap, installation and API documentation.

## Executed acceptance and reproducibility

| Acceptance area | Evidence |
|---|---|
| AUTH-01/02/04/05/06/07/10/11/14/17/18/19/20; registration, token lifecycle, admin audit/rollback | `tests/unit/test_membership_api.py` |
| AUTH-12/13/21 role and ownership portions; anonymous/four-role checks, real login sessions, cancellation persistence, logout/disable invalidation | `tests/unit/test_membership_authorization.py` |
| Migration graph, main-data preservation, upgrade/downgrade, schema constraints and auth model drift | `tests/unit/test_membership_schema.py`, `tests/unit/test_migration_completeness.py` |
| AUTH-03/08/09/15/16; MySQL uniqueness, token rotation, last-admin races, audit rollback and migration cycle | `tests/integration/test_membership_mysql.py` |
| Vue session lifecycle, envelope/error handling, malformed response rejection | `src/presentation/membership/tests/auth.test.ts` |

Local full unit suite passes the existing **80%** coverage gate; coverage is
reported in CI, not committed as generated output. SQLite HTTP tests prove roles,
ownership and sequential persistence; MySQL CI is required for transaction/race
evidence. Frontend unit tests, type-check and production build pass. A real Edge
browser with Vite and ASGI passed registration, login, reload refresh, logout,
admin create/change/disable/enable, role-specific UI and absence of credentials
from localStorage/sessionStorage. Browser QA uses synthetic SQLite data only.

```powershell
pytest tests/unit --cov=src --cov-report=term-missing
ruff check src tests
black --check src tests
mypy src
alembic heads
python scripts/export_openapi.py
```

Run MySQL integration only against the isolated `restaurant_test` database in a
testing environment, as CI does. It creates and removes synthetic tables/data.
Run `pnpm test:unit`, `pnpm type-check`, `pnpm build` from the membership frontend.

## Handoff and remaining team acceptance

Member4 should use `users.id` and shared guards rather than create another login
or user table. Loyalty rules, APIs, threshold/stacking decisions and their order
integration remain Member4/M5 work. No placeholder points or coupons are claimed.
Review submission now enforces the caller's identity, but M9/M5's existing
`OrderServiceStub` still accepts every order. Therefore AUTH-21's completed-order
business proof and the full LOY acceptance matrix remain team integration work.
Ordering/analytics APIs absent from main cannot be claimed as integrated.

The Member10 implementation and automated checks are ready for teammate review.
Shared schema/API changes still need owner review. Per CONTRIBUTING, final
completion requires green current-head CI and an approved merge into main;
this document does not claim that approval, merge, or all of T4 is 100% complete.

## 进度打卡表可粘贴内容

所属任务：**T4**。状态：PR 未合并时填 **待评审**。

完成会员注册登录、四角色权限、会话刷新退出、管理员管理与审计；按组长要求将迁移改为0004，适配主线统一格式，补齐预约及评价身份和归属校验，完成测试与文档，提交PR评审。
