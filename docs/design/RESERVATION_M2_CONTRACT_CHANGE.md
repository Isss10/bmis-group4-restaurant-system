# 预订模块（M2）契约变更说明 — 需组长协调

**作者**：KEYING CHEN (Member2)
**分支**：`feature/reservation-state-machine`（PR #34）
**日期**：2026-11-22（首版 11-21）
**状态**：完整版已提交到本地分支（`424da44` 代码 + `4460cb3` 本文档），**待推送**；组长已选**方案 A**，下一步是 M3 / M10 按第四节改测试（见 8.1 的执行顺序）

**给 M3 / M10**：PR #34 此前是**三态旧版**，因为完整版一直停在我本地没提交——这是 PR #34 与本文档对不上的原因，抱歉让你们等了。以本次推送后的代码为准。

---

## 一、一句话结论

预订模块按 `ARCHITECTURE.md` §5 / §9 和 `REQUIREMENTS.md` FR-RES-01~08 做完了（7 态状态机、离散时段、三层并发防御、占座过期、可用桌位、审计）。

但这次改动**动了 `reservations` 表结构和状态枚举**——按 `ARCHITECTURE.md` §6，这两项都是共享边界，改前必须在群里 announce。我当时直接改了，导致 M3 和 M10 的测试挂了 11 个。**这份文档就是把 announce 和改法一次补齐**，请组长定夺由谁来改。

我这边验证结果：

| 检查项 | 结果 |
|---|---|
| 预订模块自身测试（`test_reservation_repository.py`） | **94 passed** |
| 迁移守卫（`test_migration_completeness.py`） | **8 passed** |
| `ruff check` / `ruff format --check` / `black --check` | **全部通过** |
| `mypy`（CI 同参数） | 我的文件 **0 error** |
| 全量 `pytest tests/unit` | **425 passed, 13 failed, 2 skipped** |
| 端到端真实 HTTP 调用（9 组场景） | **全部符合预期**，见第九节 |

13 个失败的归属见第三节——**11 个是我造成的，2 个是既有失败**。

---

## 二、我改了什么

| 文件 | 变更 |
|---|---|
| `src/application/reservation/models.py` | 状态枚举 3 态 → 7 态；`reservation_time`/`end_time` → `slot_date`/`slot_start`/`party_size`；新增 `version`（乐观锁）、`active_slot_key`（生成列）、`updated_at` |
| `src/application/reservation/repository.py` | **`book_slot()` 单事务临界区**（锁行 → 释放过期占座 → 冲突检测 → 插入 → 审计）、`is_occupying()` 占用谓词、行锁（§5.1）、审计与业务变更同事务提交、可用桌位查询 |
| `src/application/reservation/service.py` | `create_reservation()`（规范名，`book` 保留为别名）、状态机 `ALLOWED_TRANSITIONS` 真正生效、冲突 → 20001、乐观锁 → 20004、非法流转 → 20003、占座 TTL 改用 `settings.seat_hold_ttl_seconds`、`availability()` |
| `src/presentation/api/routers/reservation.py` | 9 个端点（见下） |
| `tests/unit/test_reservation_repository.py` | 94 项测试，覆盖 FR-RES-01~08 |
| `src/data/migration/versions/20261121_1200_b7e4c1a9d2f3_reservation_slot_and_state_machine.py` | 新增迁移；**同时合并了两个迁移头** |

### 组长四项要求的落地情况

| 要求 | 实现 | 位置 |
|---|---|---|
| `create_reservation` 加事务临界区 | `BEGIN → SELECT ... FOR UPDATE → 释放过期占座 → 占用检测 → INSERT → 审计`，**全部在同一个 `session_scope` 内** | `repository.py::book_slot` |
| 冲突检测命中返回冻结码 20001 | 事务内占用检测抛 `slot_conflict()`；两个请求同时冲进空槽位时由 §5.3 唯一索引拦截，`IntegrityError` → 20001 | `repository.py::book_slot` 步骤 3-4、`service.py::_translate_db_error` |
| 占座自动过期 | 查询侧过滤（`_occupancy_filter` / `is_occupying`）+ 临界区内释放 + 全表清理接口，三层；清理任务挂掉仍正确 | `repository.py`、`POST /expire-holds` |
| 完整状态机 | 7 态，`ALLOWED_TRANSITIONS` 在**行锁内**校验（避免 TOCTOU），非法流转 20003，终态不可出 | `service.py` |

关于"临界区必须是一个事务"这点值得单独说明：改之前 expire / check / insert 是**三个独立事务**，跨事务意味着并发的 `confirm` 或清理任务可以插在我们的检测和插入之间，决策基于的是数据库已不再持有的快照。现在三步同事务，检测到的占用状态就是插入时的占用状态。M1 在 `docs/report/04-architecture.md` 图 4.5 画的正是这个顺序。

### 一个方法名的更正

我中途把服务方法叫成了 `book()`，但组长用的是 `create_reservation`，而且 **M1 的架构报告图 4.5 时序图里写的也是 `create_reservation(...)`**。已改回 `create_reservation` 为规范名，`book` 保留为别名（`book = create_reservation`，同一个函数对象，有测试断言），这样 M4/M7 的并发测试和 M1 的报告都不用动。

### 需求覆盖

| 需求 | 实现 | 验证 |
|---|---|---|
| FR-RES-01 可用桌位 | `GET /api/v1/reservations/availability?slot_date=` | 6 项测试 |
| FR-RES-02 创建即 HELD + TTL | `POST /api/v1/reservations`，TTL 取自配置（600s） | 5 项测试 |
| FR-RES-03 冲突拦截 20001 | 单事务临界区 + 生成列 `UNIQUE(active_slot_key)` | 8 项测试，含绕过应用层检查直接写库 |
| FR-RES-04 占座过期 | 查询侧过滤 + 临界区内释放 + 清理接口 | 7 项测试 |
| FR-RES-05 状态机 20003 | `ALLOWED_TRANSITIONS` 在**行锁内**校验 | 12 项测试 |
| FR-RES-06 权限隔离 | 顾客只见/只能操作自己的；员工见全部 | 6 项测试 |
| FR-RES-07 NO_SHOW 独立态 | 独立终态，no-show 率可算 | 2 项测试（含端到端算出 0.5） |
| FR-RES-08 审计 | 每次写入一行，含 actor / before / after / request_id | 10 项测试 |
| 临界区原子性（§5.1/5.4） | `book_slot` 单事务 | 5 项测试 |
| 占用谓词双实现一致 | `is_occupying`（Python）≡ `_occupancy_filter`（SQL） | 9 项测试，逐状态对拍 |

### 端点清单

```
GET    /api/v1/reservations/availability   顾客   可用桌位（FR-RES-01）
POST   /api/v1/reservations                顾客   创建预订（HELD）
POST   /api/v1/reservations/book           顾客   同上，别名（并发测试用）
GET    /api/v1/reservations                全部   列表（员工见全部，顾客只见自己）
GET    /api/v1/reservations/{id}           全部   详情
POST   /api/v1/reservations/{id}/confirm   顾客   HELD → CONFIRMED
POST   /api/v1/reservations/{id}/cancel    顾客   取消
PATCH  /api/v1/reservations/{id}/status    员工   任意合法流转
POST   /api/v1/reservations/expire-holds   员工   手动触发占座清理
```

---

## 三、CI 为什么会红：13 个失败的精确归属

CI 的 `test-unit` 作业跑**全量** `tests/unit`，而 `ci-passed`（分支保护必需检查）依赖它，所以这 13 个失败会直接阻塞合并。

| 测试文件 | 归属 | 失败数 | 是我造成的吗 |
|---|---|---|---|
| `tests/unit/test_staff_api.py` | **M3** | 3 | **是** |
| `tests/unit/test_membership_authorization.py` | **M10** | 8 | **是** |
| `tests/unit/test_membership_schema.py` | **M10** | 2 | **否，既有失败** |

**关于 `test_membership_schema.py` 要说清楚**：我动手**之前**它就已经 3 failed（分支上早先那个临时迁移 `f43ea054b096` 造成的）。我改完变成 **2 failed**——我的迁移顺手修好了它的 `test_auth_migration_has_no_autogenerate_drift`。所以这 2 个不是我打破的，但其中 1 个的失败原因被我改变了（见 4.3）。

**还有一个合并后才会浮现的失败点，先说在前面**：`origin/main` 已经把 `test_membership_authorization.py` 的取消断言改成了 `data == {"status": "cancelled"}`（期望只返回一个字段），而我的 `cancel` 端点返回完整资源。这**不会让失败数变成 14**——它落在 `test_cancel_checks_owner_before_persisting_any_change` 里，那个测试已经因为 `repo.create()` 位置参数在上面 8 个里了。但 M10 修完 4.2 的改法 2 之后会紧接着撞上它，所以别以为改完签名就绿了。详见 4.2 改法 4，那里给了甲/乙两个方案请 M1 裁决。

---

## 四、需要 M3 / M10 改的地方（可直接照抄）

### 4.1 给 M3：`tests/unit/test_staff_api.py`（3 处）

**失败的测试**
- `TestListReservations::test_returns_persisted_rows_oldest_first`
- `TestUpdateReservationStatus::test_patch_persists_the_new_status`
- `TestUpdateReservationStatus::test_patch_with_an_invalid_status_is_rejected`

**改法 1 — `repo.create()` 签名变了（L155、L156、L202）**

`reservation_time` 已不存在。新签名是**全关键字参数**：

```python
# 旧
repo.create(user_id="u-1", table_id=7, reservation_time=_LATE)

# 新
from datetime import date, time, timedelta
from src.application.reservation.repository import utc_now_naive

repo.create(
    user_id="u-1",
    table_id=7,
    slot_date=date(2026, 12, 24),
    slot_start=time(19, 30),      # 必须是 30 分钟整点，见下方说明
    party_size=2,
    expires_at=utc_now_naive() + timedelta(minutes=10),
)
```

文件顶部的 `_EARLY` / `_LATE`（L49-50）是 `datetime`，需要拆成 `slot_date` + `slot_start`。**注意 `slot_start` 必须落在 30 分钟网格上**（`18:00`、`19:30` 合法；`18:17` 不合法），营业时间 `11:00`–`22:00`。原来的 `_EARLY = 18:00` 和 `_LATE = 19:30` 恰好都合法，可以直接用。

**改法 2 — 状态值 `PENDING` → `HELD`：本文件只有 L167 一处要改**

```python
# L167（TestListReservations::test_returns_persisted_rows_oldest_first）
# 旧
assert first["status"] == "PENDING"
# 新
assert first["status"] == "HELD"
```

⚠️ **L269 和 L332 虽然也出现 `PENDING`，但不要改**——我逐行核对过，这两处断言的是**订单**状态（`OrderStatus`，M5 的模块），与预订状态无关：L269 在 `TestListOrders::test_returns_persisted_orders` 里，L332 是订单状态链测试的 docstring。改错会把 M5 的测试带崩。

**改法 3 — L169 的 `reservation_time` 断言**

响应里已无此字段，改为断言 `slot_date` / `slot_start`：

```python
# 旧
assert first["reservation_time"] == "2026-12-24T18:00:00"
# 新
assert first["slot_date"] == "2026-12-24"
assert first["slot_start"] == "18:00:00"
```

**改法 4 — L237-243 那个"非法状态被拒"的测试，`SEATED` 现在合法了**

这个测试原本发 `{"status": "SEATED"}` 期望 422，因为旧枚举只有 3 个值。**现在 `SEATED` 是 7 态之一，pydantic 会放行**，请求走到业务层因 `id=1` 不存在而返回 **404**，测试失败。

改成发一个真正非法的值：

```python
response = client.patch(
    f"{RESERVATIONS_URL}/1",
    json={"status": "NOT_A_STATUS"},   # 不在 7 态词表里
    headers=waiter_headers,
)
assert response.status_code == 422
```

如果本意是测"合法枚举值但流转非法"（应该得 20003/422），那需要先建一条预订再测——这两种意图请 M3 自己定，我不代为决定。

---

### 4.2 给 M10：`tests/unit/test_membership_authorization.py`（4 处）

**失败的测试**
- `test_customer_booking_uses_verified_subject[False]` 和 `[True]`
- `test_customer_cannot_create_booking_for_another_identity`
- `test_cancel_checks_owner_before_persisting_any_change`
- `test_staff_endpoints_follow_four_role_matrix_and_logout_revocation[customer/waiter/manager/admin]`（4 个参数化）

**改法 1 — `booking()` 助手（L72-75）**

```python
# 旧
def booking(self, user_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"table_id": 7, "reservation_time": WHEN.isoformat()}

# 新
def booking(self, user_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "table_id": 7,
        "slot_date": "2026-12-24",
        "slot_start": "19:30:00",
        "party_size": 2,
    }
```

L35 的 `WHEN = datetime(2026, 12, 24, 19, 30)` 可保留或拆成两个常量。`19:30` 在网格上、在营业时间内，合法。

⚠️ **注意 4 个参数化用例会互相冲突**：它们都用 `table_id=7` + 同一时段，而唯一约束只允许一条活跃预订。如果这些用例在同一个数据库会话里跑，第 2 个会拿到 20001 而不是预期结果。需要给不同用例分配不同 `table_id` 或不同 `slot_start`。

**改法 2 — `repo.create()` 位置参数调用（L225-226）**

新签名是**全关键字**，位置参数会直接 `TypeError`：

```python
# 旧
other = repo.create(str(authorization.ids["other"]), 1, WHEN)
own = repo.create(str(authorization.ids["customer"]), 2, WHEN)

# 新
other = repo.create(
    user_id=str(authorization.ids["other"]), table_id=1,
    slot_date=date(2026, 12, 24), slot_start=time(19, 30),
    party_size=2, expires_at=utc_now_naive() + timedelta(minutes=10),
)
own = repo.create(
    user_id=str(authorization.ids["customer"]), table_id=2,
    slot_date=date(2026, 12, 24), slot_start=time(19, 30),
    party_size=2, expires_at=utc_now_naive() + timedelta(minutes=10),
)
```

（两行 `table_id` 不同，所以同一时段不冲突。）

**改法 3 — `ReservationStatus.PENDING`（L241）**

```python
# 旧
assert other_row is not None and other_row.status == ReservationStatus.PENDING
# 新
assert other_row is not None and other_row.status == ReservationStatus.HELD
```

L38 的注释 `frozen PENDING/CONFIRMED/CANCELLED` 建议一并更新为 7 态。

**改法 4 — L237 的 `"cancelled"` 断言（⚠️ 合并后才会暴露，现在看不到）**

这一条和前三条不同，**在我当前分支上测不出来**，但合并到最新 main 后会失败，所以单独说明。

`origin/main` 上这一行已经被你们改成了：

```python
assert response.json()["data"] == {"status": "cancelled"}   # origin/main 版本
```

而我的分支上还是旧版 `data["status"] == "cancelled"`。合并时 Git 会取 main 的版本，于是断言变成"整个 `data` 只等于 `{"status": "cancelled"}`"。

但我的 `cancel` 端点实际返回的是**完整的预订资源**（11 个字段）：

```
['created_at', 'expires_at', 'id', 'party_size', 'slot_date', 'slot_start',
 'status', 'table_id', 'updated_at', 'user_id', 'version']
```

所以合并后这一行会失败。**这是一个需要 M1（REST API 契约负责人）裁决的设计问题，不是单纯的机械适配**：

| 选项 | 说明 |
|---|---|
| **甲**：M10 把断言改回 `data["status"] == "cancelled"` | 我推荐这个。返回完整资源是更常见的 REST 做法，前端取消后可以直接用返回值更新本地状态，不用再发一次 GET；而且 `confirm` / `cancel` / `PATCH status` 三个端点返回形状一致。改动只有 1 行。 |
| 乙：我把 `cancel` 的响应改成只返回 `{"status": ...}` | 也能过，但三个写端点的返回形状就不一致了（`confirm` 和 `PATCH status` 仍返回完整资源），前端要区别对待。 |

请组长转给 M10 和 M1 定。**在他们回复之前我不擅自改**，因为这两个方向都合理，而返回形状属于冻结的 REST 契约。

⚠️ 另外提醒 M10：如果选甲，`test_staff_endpoints_follow_four_role_matrix_and_logout_revocation` 里 L329-333 那段也用 `booking()` 打 `POST /reservations`，会受改法 1 影响。

---

### 4.3 给 M10：`tests/unit/test_membership_schema.py`（2 处，既有失败）

**改法 1 — L149 迁移头断言写死了具体 revision id**

```python
# 旧
assert script.get_heads() == ["97393cdd0b6c"]
```

现在头是 `b7e4c1a9d2f3`（我的合并迁移）。**这个断言任何人加迁移都会破**，建议改成断言"只有一个头"而不是写死 id：

```python
heads = script.get_heads()
assert len(heads) == 1, f"expected a single migration head, got {heads}"
```

L150-156 的 `walk_revisions()` 链条同理，需要在列表里加上 `b7e4c1a9d2f3`，或者改成断言长度/包含关系而非写死全链。

**改法 2 — L178-186 用 ORM 模型往 `0003` 的表里插数据**

这个测试 `upgrade` 到 `0003` 后，用**完整的当前 ORM 模型**插入行：

```python
connection.execute(insert(Reservation), {
    "id": 51, "user_id": "...", "table_id": 3,
    "reservation_time": datetime(2026, 11, 23, 12),   # ← 0003 之后已被我删除
    "status": ReservationStatus.CONFIRMED,
    "created_at": datetime(2026, 11, 8, 12),
})
```

基线失败信息是 `table reservations has no column named end_time`（分支上那个临时迁移已加列），我改完变成 `has no column named party_size`。**根因是同一个**：`0003` 的表结构和当前 ORM 模型不一致，而这个测试假设它们一致。

建议改成插入**裸 SQL 字面量**、只写 `0003` 实际拥有的列，而不是借 ORM 模型：

```python
connection.execute(
    sa.text(
        "INSERT INTO reservations (id, user_id, table_id, reservation_time, status, created_at) "
        "VALUES (51, 'existing-main-customer', 3, '2026-11-23 12:00:00', 'CONFIRMED', '2026-11-08 12:00:00')"
    )
)
```

然后校验时也读裸列而非 ORM 对象。**但这样这个测试就验不到 `slot_date` 的回填了**——是否要覆盖回填路径，请 M10 定夺；如果需要，我可以配合。

---

### 4.4 一个我没统一的地方：状态值大小写

| 路由 | 返回 | 断言它的测试 |
|---|---|---|
| `routers/reservation.py`（我的） | **小写** `"held"` | M10 的 `test_membership_authorization.py` L237（断言 `"cancelled"`） |
| `routers/staff.py`（M3 的） | **大写** `"HELD"` | M3 的 `test_staff_api.py` L167（断言 `"PENDING"`，改后应为 `"HELD"`） |

`staff.py` 没有做任何小写化处理，枚举值原样序列化，所以是大写；我的 `reservation.py:156` 显式调了 `.lower()`。

两边都有既有测试断言，改任何一边都会破对方的测试，所以我**保留了现状**，只是把它记在这里。按 `ARCHITECTURE.md` §6，REST API 契约归 **YAN ZHANG (M1)**，统一大小写需要一个契约 PR + 三个前端负责人在场。请组长决定是否单独立项。

---

## 五、附带发现：并发测试其实没在 CI 里跑

这条和我的工作无关，但影响 Objective (d) 的验收，一并报告。

`tests/concurrency/test_concurrent_booking.py` 只有 `pytestmark = pytest.mark.skipif(...)`，**没有 `concurrency` marker**。而 CI 的 `test-integration` 作业用 `-m "integration or concurrency"` 过滤，所以它被 deselect 了：

```
$ pytest tests/integration tests/concurrency -m "integration or concurrency" --collect-only -q
tests/integration/test_membership_mysql.py::test_membership_placeholder
1/10 tests collected (9 deselected)
```

后果：

- **好的一面**：它不会让 CI 变红（所以第 3 节的 13 个失败里没有它）。
- **需要修的一面**：`ARCHITECTURE.md` §5.4 说这个测试是"Objective (d) 在仓库里最重要的产物"，11/30 要验收"50 并发只有 1 个成功"。**它现在一次都没被 CI 执行过。** 归 M4 (GEMAN MENG) / M7 (JIAYI TAN)。

另外它有两个已知问题，等加上 marker 就会暴露：

1. **不带鉴权头**。`_one_booking()` 直接 `client.post("/api/v1/reservations/book", json=payload)`，没有 `Authorization`。我的端点要求 customer 令牌，所以会全部 401，断言 `wins == 1` 会失败。
2. **好消息**：它打的端点和字段（`POST /reservations/book` + `slot_date`/`slot_start`/`party_size`）**和我的实现完全一致**——我实现时是照着这个测试对齐的，所以字段层面不用改。

给 M4/M7 的最小改法：文件顶部加 `pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(...)]`，并在 `_one_booking` 里带上一个 customer 令牌。

---

## 六、需要组内确认的事项

按 `ARCHITECTURE.md` §6 和《组员快速上手指南》§五，以下是我**已经改了**的共享边界，事后补 announce：

| 共享边界 | 归属 | 我改了什么 | 影响谁 |
|---|---|---|---|
| 预订状态机 | KEYING CHEN（我） | 3 态 → 7 态 | M3 员工后台、M6 分析（no-show 率）、M9 评论（`COMPLETED` 是评论资格门槛） |
| 数据库表结构 | YUANYUAN XUE (M8) | 新增迁移，改 `reservations` 列 | M3、M10、M8 |

**请 M8 特别看一眼迁移文件**：`down_revision` 是一个**元组** `("f43ea054b096", "97393cdd0b6c")`，因为合并 main 之后出现了两个迁移头（我的分支一个、你们的 M5 点餐表一个），`alembic upgrade head` 在多头下会拒绝运行。我这个迁移是合并点。如果 M8 认为应该用 `alembic merge` 单独生成一个空合并迁移，我可以改。

还有两个我自己**拍的假设**，不在冻结契约里，请确认：

1. **营业时间 `11:00`–`22:00`，最后入座 `21:30`**（`service.py` 的 `OPENING_HOUR` / `CLOSING_HOUR`）。不在契约里，也不在《指南》那 6 个待拍板项里。改它只影响可用时段网格。
2. **`DEFAULT_TABLE_IDS = range(1, 21)`**（20 张桌）。仓库里**没有桌位目录表**，`reservations` 只存一个裸 `table_id`。FR-RES-01 要求返回"桌号、座位数、区域"，这三样**目前无处可读**，所以 `availability` 只返回 `table_id` + 空闲时段，前端拿不到桌位属性。需要 M8 建 `dining_tables` 表后我再接上。

---

## 七、MySQL 专属行为未在本机验证

本机没有 Docker，3306 未开，`.env` 不存在，所以以下**只在 SQLite 上验证过**，MySQL 部分标注待验证：

| 已验证（SQLite 实测） | 待验证（需真实 MySQL 8） |
|---|---|
| 生成列 `CASE WHEN ... CONCAT` 能建出并正确计算 | 生成列 DDL 在 MySQL 8 的语法（我按 §5.3 的写法） |
| `UNIQUE(active_slot_key)` 拒绝重复活跃预订、允许多个 NULL | `IntegrityError` 的原文是否含 `uq_active_reservation` |
| 状态翻转后 key 自动重算、槽位释放 | ENUM 三步收窄（widen → rewrite → narrow）在严格模式下 |
| 迁移链 SQLite 上 up / downgrade base / up 全通 | `TIMESTAMP()`、`SEC_TO_TIME()`、`TIME_TO_SEC()` 回填 |
| 乐观锁 `version` 自增 | `StaleDataError` → 20004 的真实并发触发 |

**一个已知的方言差异**：`CONCAT` 渲染 `TIME` 列时，MySQL 给 `19:30:00`，SQLite 给 `19:30:00.000000`。约束本身在各自方言内自洽（都拒绝重复），所以正确性不受影响；只有 `slot_key()` 生成的**冲突提示文本**在两边字节不同。这点已写进 `models.py` 的 docstring，测试用 `startswith` 断言而非全等。

CI 的 `test-integration` 作业有真实 MySQL 8 服务并跑 `alembic upgrade head` / `downgrade base`，所以上表右列会在 CI 上得到验证——**前提是合并前先把第 3 节的 11 个失败处理掉，否则单元作业先红，看不出集成的结果**。

---

## 八、请组长定夺

### 8.1 最关键的一个：那 11 个失败由谁改，什么时候改

这不是"改不改"的问题——**必须有人改**，因为 CI 的 `test-unit` 跑全量、`ci-passed` 依赖它，不改就合不进 main。我按约定没动别人的文件，改法已逐行写在第四节。

**执行顺序（组长已选 A，此处更正本文档早先写反的顺序）**

早先版本把方案 A 写成"M3/M10 各自改完、我再开 PR"，那是个死锁：他们要改的断言（`PENDING`→`HELD`、`reservation_time`→`slot_date`、`repo.create()` 签名）必须以我的最终契约为依据，看不到我的代码就没法改。正确顺序是：

1. **我先推完整版到 `feature/reservation-state-machine`**（PR #34）← 已完成，见提交 `424da44` / `4460cb3`
2. M3、M10 各自在自己分支上按第四节改，**改完再合进 main**
3. 两边都绿之后，PR #34 才具备合并条件

在第 2 步完成前，**PR #34 的 CI 必然是红的，这是预期状态、是工作清单，不是缺陷**。

工作量：**M3 约 4 处、M10 约 6 处，绝大部分是机械适配**（换字段名、换枚举值、换迁移头断言），照着抄即可。只有 **1 处涉及设计判断**：4.2 改法 4 的取消响应形状，`origin/main` 的断言期望 `data` 只含 `{"status": ...}`，而我返回完整资源——这一处需要 M1 在甲/乙之间裁决，不是 M10 自己能定的。

三个可选排期（组长已选 A，保留记录）：

| 方案 | 做法 | 代价 |
|---|---|---|
| **A（已采纳）** | 我先推完整版，M3、M10 照第四节改，两边都绿再合并 | 需要两位同学跟进，约 1 天；PR #34 在此期间 CI 红 |
| B | M3/M10 在我的分支或紧随其后的 PR 里改 | 与 A 实际等价，只是分支归属不同 |
| C | 破例由我代改那 11 处，PR 一次全绿 | 动了别人文件，可能与 M3/M10 在途工作冲突；且 4.2 改法 4 那个设计问题我仍需 M1 先裁决，否则代改方向可能错 |

第四节请按人转交：4.1 → M3（HE RANXI），4.2 / 4.3 → M10（RONG CONG），4.2 改法 4 → M1（YAN ZHANG）裁决。

### 8.2 其余四项

1. **第 4.4 的状态大小写**：我的路由返回小写、M3 的 staff 路由返回大写，两边都有既有测试断言。统一需要一个契约 PR（归 M1 YAN ZHANG）+ 三个前端负责人在场。要不要立项？
2. **第 5 节的并发测试 marker**：`tests/concurrency/test_concurrent_booking.py` 缺 `concurrency` marker，现在被 CI 过滤掉、一次都没跑过。归 M4（GEMAN MENG）/ M7（JIAYI TAN），谁去补？
3. **第 6 节的两个假设**：营业时间 `11:00`–`22:00`、20 张桌（`DEFAULT_TABLE_IDS`）是我拍的，不在冻结契约里。要不要改成配置项或由组内定？
4. **`dining_tables` 表**：FR-RES-01 要求返回桌号/座位数/区域，仓库里没有这张表，我目前只能返回 `table_id`。需要 M8（YUANYUAN XUE）建表后我再接上，还是降级需求只做 `table_id`？

---

## 九、端到端实测记录

评审意见里明确说过"这个仓库已经三次出现 CI 全绿但代码跑不通"，所以合并前我用 `TestClient` 打了真实 HTTP 请求（SQLite 内存库），不是只看单元测试通过。

**预订与冲突**

| # | 请求 | 结果 |
|---|---|---|
| 1 | `POST /reservations/book`（并发测试用的端点） | 200，`code 0`，`status: held` |
| 2 | 同槽位第二次 | **409，`code 20001`，"该时段该餐桌已被预订"** |
| 3 | 查库 | **`reservations` 只有 1 行**，`audit_logs` 1 行 |
| 4 | 不同槽位 | 200，`code 0` |
| 5 | `POST /{id}/confirm` | 200，`status: confirmed`，`expires_at: null` |

**状态机**

| # | 请求 | 结果 |
|---|---|---|
| B | 员工 `HELD → SEATED`（跳过 CONFIRMED） | **422，`code 20003`**，`errors: [{field: status, detail: "HELD -> SEATED is not permitted"}]` |
| C | 员工 `HELD → CONFIRMED` | 200，`confirmed` |
| D | 员工 `CONFIRMED → NO_SHOW` | 200，`no_show` |
| E | `NO_SHOW → CONFIRMED`（终态） | **422，`code 20003`** |
| F | 员工把状态改成 `EXPIRED` | **422，`code 20003`**（只允许清理任务产生） |
| G | 非法枚举值 `NOT_A_STATUS` | 422，`code 10001` |
| H | 不存在的预订 id | 404，`code 40001` |

**权限（OWASP A01）**

| # | 请求 | 结果 |
|---|---|---|
| A | 顾客打员工端点 `PATCH /{id}/status` | 403，`code 30003`（角色守卫先拦） |
| 7 | `cust-2` 取消 `cust-1` 的预订 | **403，`code 30003`**，且库里该行未被改动 |
| 8 | 无令牌 | 401，`code 30001` |
| J | 顾客调 `POST /expire-holds` | 403，`code 30003`（员工端点） |

**可用桌位与清理**

| # | 请求 | 结果 |
|---|---|---|
| 9 | `GET /availability?slot_date=2026-12-24` | 20 张桌，7 号桌空闲时段 20 个（22 − 2 个已占），`19:30` 已不在空闲列表 |
| J | 员工 `POST /expire-holds` | 200，`{expired_count: 0}` |

**一条额外的好消息**：`PATCH /api/v1/staff/reservations/{id}`（M3 的员工后台路由）打同一个非法流转，也返回 **20003**。说明状态机是落在服务层的，全系统共用一套规则，不是只在我自己的端点生效——这正是 ARCHITECTURE.md §9 要求的"transitions must be validated in the service layer"。

