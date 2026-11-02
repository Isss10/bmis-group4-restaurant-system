# 会员认证前端

独立 Vue 3 / TypeScript / Pinia / Element Plus 入口，不改动原有菜单页面。

```powershell
cd src/presentation/membership
pnpm install --frozen-lockfile
pnpm dev
```

浏览器访问 `http://localhost:5173`。同时在仓库根目录运行后端：

```powershell
uvicorn src.presentation.api.main:app --reload --host 127.0.0.1 --port 8000
```

Vite 将 `/api` 代理到后端。后端 `APP_CORS_ORIGINS` 需包含实际访问的前端 origin；默认
`http://localhost:5173`，若改用 `127.0.0.1` 访问也须加上对应 origin。

```powershell
pnpm type-check
pnpm test:unit
pnpm build
```

生产部署应使用 HTTPS，静态文件与 `/api` 置于同一站点，设置正确的后端 origin 允许列表。
`dist/` 是本地构建产物，不提交到 Git。生产 API 的刷新 cookie 使用 Secure；本地开发环境
允许 HTTP。页面刷新通过 HttpOnly cookie 恢复会话；access token 只在内存中保存。

页面包括顾客注册、四角色登录、个人账号资料和管理员账号管理。积分/等级/优惠券展示
等待对应业务模块接入；本页面不会把尚未实现的积分或等级显示成真实数值。
