# 餐厅预订与点餐系统 — 用户手册

JC2001 BMIS Group 4 · 安装与操作指南（维护人：JIAYI TAN）

## 1. 系统简介
面向中小型餐厅的在线预订 + 点餐原型：并发安全订座、菜单浏览与下单、会员积分、评价、经理数据看板。

## 2. 环境要求
- Python 3.11
- MySQL 8.0（InnoDB）
- Node.js 18+（前端 Vue 3）

## 3. 后端安装与启动
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env   # 填入 APP_JWT_SECRET_KEY 与数据库连接
python -m alembic upgrade head
uvicorn src.presentation.api.main:app --reload
