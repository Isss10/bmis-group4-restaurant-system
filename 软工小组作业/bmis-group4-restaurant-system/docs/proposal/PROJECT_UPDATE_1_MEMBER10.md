# Project Update 1 — Member10 contribution

Reporting date: 12 October 2026. Milestone: Requirement & Design.
Module: Membership & Loyalty, Objective (c). Implementation deadline: 23 November 2026.

## Work prepared for this update

Member10 prepared the registration, login and role-based access-control design for the
membership module. The work uses the revised proposal and the repository's current allocation:
Member10 owns authentication and role management; Member4 owns points, tiers and coupons.
The older phase sheet's local-file storage and Member10 testing/manual allocation are superseded
for this contribution. The supplied technology-selection document is followed throughout.

The design includes customer-only public registration, four-role permissions, ownership checks,
access/refresh lifecycle, account deactivation and role-change invalidation, audit transactions,
three-tier component boundaries, candidate REST interfaces and relational entities. It includes
use-case, architecture, authentication-sequence and relationship diagrams plus page wireframes.
The acceptance plan traces authentication, permission and audit requirements to normal, failure,
boundary and concurrent scenarios, and defines the integration handoff with Member4.

## Evidence

| Deliverable | Evidence |
|---|---|
| Requirements, use cases and component/data design | [MEMBERSHIP_MEMBER10.md](../design/MEMBERSHIP_MEMBER10.md) |
| Test traceability and implementation gates | [MEMBERSHIP_MEMBER10_ACCEPTANCE.md](../testing/MEMBERSHIP_MEMBER10_ACCEPTANCE.md) |
| Update 1 contribution | This document |

## Status and dependencies

The Member10 design package is prepared for review. Production endpoints, migrations, Vue pages
and database-backed acceptance tests are not implemented by this documentation change.
No claim is made that Project Update 1 has been submitted to the course or that the group has
approved the proposed contracts. Repository completion still requires green CI and an approved merge.

Before implementation, Member1 must reconcile the standards manual, response/error contract,
router location, refresh transport and token revocation strategy. Member8 must review the user
and session schema and the administrator-concurrency invariant. Member4/Member5 must confirm
points expiry/allocation, tier thresholds and coupon calculation/transaction rules.
The existing requirements and contract-alignment branches were read as review material;
their changes are not treated as already merged into main.

## Next implementation work

Implement registration/login/current-user services after contract and schema approval; then
refresh/logout and administrator role/status management with transactional audit logging.
Build Vue login/registration/account screens and integrate Member4's loyalty data. Execute the
planned unit, API, MySQL integration and concurrency tests; update generated OpenAPI and operating
instructions before the 23 November implementation milestone.

## 可用于汇报的中文说明

本阶段完成了会员认证与权限的需求和设计资料：明确 Member10 与 Member4 的分工，
整理四角色权限、顾客注册、登录/刷新/退出流程、账号停用与角色变更后的会话失效，
绘制用例、三层结构、数据关系与登录时序，并给出页面线框和验收场景。
下一步先与公共接口、数据库和积分模块负责人核对契约，再进入编码与联调。
当前交付是待评审的设计材料，不能报告为功能已实现或课程进度更新已提交。
