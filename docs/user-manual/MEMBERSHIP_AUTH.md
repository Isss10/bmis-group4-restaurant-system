# 会员认证与账号管理操作说明

适用：Member10 / T4 的注册、登录、权限与账号管理。积分、等级、优惠券由 Member4 接入。

## 1. 后端准备

在仓库根目录，使用 Python 3.11（项目也支持 3.12）安装环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

如果已有 `.env`，保留现有文件并核对配置。设置 MySQL 8 地址、数据库名称、用户名和密码，
数据库需事先建立。生成独立 JWT 密钥填到 `.env` 的 APP_JWT_SECRET_KEY，不提交 `.env`。

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
alembic upgrade head
```

**第一次部署先创建管理员，再开放顾客注册**：

```powershell
python scripts/bootstrap_admin.py --email admin@example.com --display-name Administrator
```

按提示输入并确认密码（不少于 12 字符，UTF-8 不超过 72 字节），屏幕不会显示密码。
`admin@example.com` 是示例地址，请替换为本项目的管理员地址。没有默认账号或默认密码。
该命令只接受空 users 表，不能用来给已有账号提权；后续员工由管理员在页面创建。
如果测试库先注册了顾客，应新建独立开发库重新迁移与初始化，避免删除已有数据。

```powershell
uvicorn src.presentation.api.main:app --reload --host 127.0.0.1 --port 8000
```

开发环境可打开 http://127.0.0.1:8000/docs 调试；生产模式隐藏该入口。
生产配置仍遵守仓库要求：强密钥、数据库密码、明确 CORS allow-list、HTTPS。

## 2. 前端准备

认证入口是独立 Vue 3 项目，已有菜单页面保持原样。安装 Node.js 22 和 pnpm 11，
在新终端执行：

```powershell
cd src/presentation/membership
pnpm install --frozen-lockfile
pnpm dev
```

打开 http://localhost:5173 。Vite 把 /api 请求代理到 127.0.0.1:8000。
若使用 127.0.0.1:5173 或自定义地址访问，需把该地址加入 APP_CORS_ORIGINS。
请使用不同浏览器会话测试不同账号，避免同一浏览器 cookie 相互覆盖。

## 3. 顾客使用

1. 选择“注册”，填写邮箱、显示名、密码并提交。系统只注册顾客，不提供角色选择。
2. 注册成功后登录。页面显示本人的账号信息和角色。
3. 刷新页面时，系统通过安全 cookie 恢复会话；令牌过期或账号停用后需要重新登录。
4. 点击“退出登录”，当前浏览器会话失效；其他设备会话保持。

账号已存在时请使用原账号登录。错误密码、未知账号和停用账号统一显示登录失败。
频繁尝试会收到 429，请等待一分钟再试。尚未接入的积分等信息不会显示成真实余额。

## 4. 管理员使用

1. 使用初始化的管理员账号登录，打开账号管理区。
2. 查看分页账号列表；选择“创建账号”填写员工信息和角色。
3. 修改角色或启用/停用前，核对确认框内的目标和影响。成功后目标账号全部旧会话失效。
4. 如果表单版本已过期，重新加载列表再操作；系统会阻止移除最后一个有效管理员。

服务员、经理及顾客均不能调用管理员接口。账号创建、角色与状态变更会写审计，
与业务变更一同提交。遇到错误请保留页面 request_id，不要发送密码、cookie 或令牌。

## 5. 检查与交接

```powershell
pytest tests/unit
ruff check src tests
black --check src tests
mypy src
```

认证 MySQL 集成/并发测试仅允许 testing 环境、独立数据库 restaurant_test。
这些测试会建立和清理测试表，不能指向有实际业务数据的库。
CI 使用专用 MySQL 服务执行；本机未配置 MySQL 时会明确 skip。

正式部署：前端 `pnpm build` 后把 dist 与 /api 放在同一 HTTPS 站点；构建产物不提交。
旧无会话 JWT 不再可用，需要通过登录接口获得新令牌。接口及跨模块交接见
[认证 API 文档](../api/MEMBERSHIP_AUTH.md)。数据库 rollback 保留审计表和历史记录。
