# Member10：认证与权限验收计划

日期：2026-10-12；关联 [设计](../design/MEMBERSHIP_MEMBER10.md)。
这是未来实现的验收计划，不是已执行的测试报告。M10 负责认证/权限；M4 负责积分/券；
M7/M4 负责最终集成。业务码须以 M1 最终契约为准，下面 300xx 引用契约对齐评审稿。

## 1. 测试环境与方法

- Python 3.11、pytest/pytest-asyncio、项目声明的 HTTP 测试客户端和 pytest-cov。
- 单元测试使用 repository fake；接口测试使用 FastAPI TestClient/依赖替换。
- 唯一约束、事务、行锁、刷新及角色管理并发测试必须使用专用 MySQL 8 InnoDB。
- 所有账号、邮箱、订单均为合成数据；JWT key 每轮随机生成，不上传真实凭证。
- 时间敏感测试注入固定 UTC clock，覆盖到期前、恰好到期、到期后。
- 下面每个用例均断言 HTTP、response DTO、DB 状态；失败不得造成部分持久化。

## 2. 需求到验收场景

| ID | 需求 | 场景/输入 | 预期 | 级别 |
|---|---|---|---|---|
| AUTH-01 | FR-MEM-01 | 合法顾客注册 | 一个 customer；DB 仅含 hash；输出无密码/hash | 单元+集成 |
| AUTH-02 | FR-MEM-01/02 | 注册提交 role=admin/waiter 或 is_active/auth_version | 拒绝额外字段；不能提权 | 接口 |
| AUTH-03 | FR-MEM-01 | 两个并发请求注册相同规范化邮箱 | 恰好一成功；DB 一行；另一返回受控冲突 | MySQL 并发 |
| AUTH-04 | FR-MEM-01 | 空邮箱、无效邮箱、超长昵称、超过 72 UTF-8 字节密码 | 校验失败；DB 无新增；不静默截断 | 单元+接口 |
| AUTH-05 | FR-MEM-01 | customer/waiter/manager/admin 分别合法登录 | token role 来自 DB，access 默认 3600 秒 | 参数化接口 |
| AUTH-06 | FR-MEM-01 | 错密码、未知邮箱、停用账号 | 统一失败形状；无令牌；未知账号也做 dummy 验证 | 单元+接口 |
| AUTH-07 | FR-MEM-01 | 缺 Bearer / 过期 / 错签名 / alg=none / 缺 claim / 未知 role | 401；缺凭证 30001，其余 30002；无内部错误泄漏 | 接口 |
| AUTH-08 | FR-MEM-01 | 正常 refresh，随后重用旧 refresh | 新令牌可用；旧令牌失败且该 session 撤销 | MySQL 集成 |
| AUTH-09 | FR-MEM-01 | 同一 refresh 两个并发请求 | 至多一次轮换成功，无两个有效后继；重放策略明确 | MySQL 并发 |
| AUTH-10 | FR-MEM-01 | 到期/撤销 refresh；用 refresh 访问普通接口 | 均拒绝；无新会话 | 接口+集成 |
| AUTH-11 | FR-MEM-01 | 当前会话 logout 两次 | 幂等成功；access/refresh 均不可再用；其他会话不受影响 | 集成 |
| AUTH-12 | FR-MEM-02 | 顾客猜测另一顾客 id；伪造 body user_id | 不能读写他人预约/资料/积分/券 | 跨模块接口 |
| AUTH-13 | FR-MEM-02 | 四角色逐项访问设计权限矩阵 | 允许项成功；不允许项 403/30003；匿名 401 | 参数化接口 |
| AUTH-14 | FR-MEM-02/06 | admin 修改 role 或停用账号后立即用旧 token | 旧 access/refresh 拒绝；新登录采用当前角色/状态 | 集成 |
| AUTH-15 | FR-MEM-06 | 管理事务写审计失败 | 用户变更及会话撤销均回滚，无部分更新 | MySQL 故障注入 |
| AUTH-16 | FR-MEM-06 | 两个 admin 同时尝试降级最后的 active admins | 至少保留一个 active admin；受控冲突 | MySQL 并发 |
| AUTH-17 | FR-MEM-01/02 | 外站 Origin、无 CSRF cookie refresh/logout | 拒绝；会话状态不变 | 接口 |
| AUTH-18 | FR-MEM-01 | 登录超过批准的限流阈值 | 429；不给 token；业务码按 M1 契约 | 接口 |
| AUTH-19 | FR-MEM-06 | 角色变更携带过期 version；成功变更 | 旧 version 冲突无变更；成功有 actor/对象/before/after/request_id | 集成 |
| AUTH-20 | FR-MEM-01/06 | 检查响应、JWT、应用日志、审计日志、数据库会话 | 无密码/hash/token 原文泄漏；cookie 安全标志正确；DB 仅存 token 摘要 | 安全检查 |
| AUTH-21 | FR-MEM-02 | manager 作为 customer 发起评价；customer 冒充有订单 | 无顾客权限及未完成订单均拒绝，管理角色不绕过业务校验 | 跨模块接口 |

所有允许/拒绝检查直接发 HTTP，不能仅靠 Vue 路由测试。role enum 不自动继承，
每个模块必须显式列出 staff/manager/admin 集合；匿名刷新使用 refresh 凭证单独验证。
测试矩阵覆盖错误路径，不能只证明“合法顾客登录成功”。

## 3. 与 Member4 的交接验收（M4 实施）

| ID | 场景 | 预期 |
|---|---|---|
| LOY-01 | 同一 order-completed 事件投递两次 | 仅一个 EARN 业务事件，不重复加分 |
| LOY-02 | 一批赚取 100 分，兑换 40 分，剩余 60 分到期 | 到期后余额 0，不为 -40；账本和批次分配均可解释 |
| LOY-03 | 赚取/兑换/过期均并发发生 | 同事务计算；不透支，不丢失更新，不重复过期 |
| LOY-04 | 等级指标恰好等于阈值及上下边界 | 使用批准的指标和阈值，不假定数值 |
| LOY-05 | 两个订单并发使用同一 user_coupon | 一次成功，另一次受控拒绝，订单和券同事务 |
| LOY-06 | 100 元订单，批准采用 10% 后减 20 元 | 70.00；EXCLUSIVE 不叠加，折扣不越原价；此示例依赖规则批准 |
| LOY-07 | 券属于他人/恰到期/不满足门槛/订单取消 | 按冻结契约拒绝或补偿，不越权、不失账 |
| LOY-08 | 手工调整/发券/兑换事务失败与成功 | 失败回滚；成功仅一条对应审计，无敏感字段 |

## 4. 设计核对与实施验收门槛

10/12 设计材料：需求/分工、用例视图、角色矩阵、三层模块、接口候选、关系模型、
认证时序、异常路径、线框、测试追踪和 Update 1 内容均已准备，待团队评审。

实施前评审清单：

- [ ] M1：取得标准手册，冻结角色矩阵、路径/DTO、envelope、冲突及限流业务码。
- [ ] M1/M10：确认 refresh 传输形式、CSRF、轮换/重放策略、JWT session/version 扩展。
- [ ] M8：确认 users/session/used-token 模型、邮箱唯一性与 admin 并发约束，新建 migration。
- [ ] M4/M5：冻结积分批次分配、等级指标/阈值、券叠加与金额舍入/取消规则。
- [ ] M1：统一路由所在层及挂载方式，不向 application 引入 FastAPI。

11/23 实现验收：上述 AUTH 场景通过，M4 交接项通过，OpenAPI 从运行中的路由导出，
pytest 覆盖率遵守仓库总覆盖门槛；CI 全绿、同学审核后由团队合并。
用例在 `tests/unit/`、`tests/integration/` 实现；MySQL 并发证明归 `tests/concurrency/`。
本次只有文档，无运行时代码变更，因此未将计划中的测试标记为 PASS。
