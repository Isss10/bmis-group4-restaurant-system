# Member10 — 12 November early-delivery contribution

> Historical early-delivery record. Current migration, contract and integration
> results are in [the November 23 delivery](PROJECT_UPDATE_MEMBER10_NOV23.md).

Task: **T4 Membership & Loyalty**, jointly assigned to Member10 and Member4.
This contribution implements Member10's authentication and permission slice.
12 November is the user's requested early delivery; the proposal's full T4
deadline remains 23 November 2026. The 12 October design contribution was merged
as PR #5 before this implementation began.

## Delivered behaviour

- Customer-only public registration and four-role login using existing bcrypt/JWT helpers.
- Current identity/profile, absolute-expiry refresh cookies with rotation and replay revocation,
  idempotent logout and live session checks shared by existing role guards.
- Administrator account listing/creation, role/status changes with version conflicts,
  immediate old-session invalidation, last-active-admin protection and transactional audit.
- New relational migration after 0001; old migrations are unchanged and existing audit history
  survives downgrade. First-admin bootstrap reads its password privately from the terminal.
- Standalone Vue 3 / TypeScript / Pinia / Element Plus entry for registration, login, account
  details and admin operations; access tokens stay in memory and refresh is single-flight.
- Generated OpenAPI, API/operating documentation, security/HTTP acceptance tests, MySQL
  concurrency/migration tests and a separate CI check for the new frontend.

## Evidence and limits

| Evidence | Location |
|---|---|
| API contract and security/transaction decisions | [API](../api/MEMBERSHIP_AUTH.md) |
| Installation and operation | [User guide](../user-manual/MEMBERSHIP_AUTH.md) |
| Authentication HTTP and rollback scenarios | `tests/unit/test_membership_api.py` |
| Schema and migration checks | `tests/unit/test_membership_schema.py` |
| Real-MySQL concurrency and migration tests | `tests/integration/test_membership_mysql.py` |
| Browser state and session tests | `src/presentation/membership/tests/` |

The main branch's response shapes remain compatible. Unmerged contract-alignment
changes are not treated as approved. M1/M8 review is needed for the shared auth and
schema additions before merge. Existing unmounted prototype routers remain with
their owners; this contribution does not claim full-system integration is finished.
Points, tiers and coupons remain Member4's implementation, using users.id as the
identity boundary. No fake loyalty balances are displayed. No course submission
or group approval is claimed by this document.

## 进度表可用说明（100 字内）

完成T4中注册登录、四角色权限、令牌刷新退出及管理员账号管理，加入会话失效、审计与数据库迁移；完成Vue页面、接口文档及自动测试，提交PR评审。积分等级优惠券由Member4继续接入。

所属任务填 **T4**。PR 待同学审核时填“待评审”；完成度按整个 T4 及小组填写规则计算，
本人的认证部分完成不等于整个会员模块 100%。
