# 项目交接与新环境搭建

更新：2026-11-13。

## 1. 当前基线

- 功能范围：F01—F16 已完成正式页面与业务流程。
- 后端：Python 3.12、FastAPI、SQLAlchemy、Alembic、OR-Tools CP-SAT。
- 前端：Vue 3、TypeScript、Element Plus、Vite。
- 数据库：MySQL 8.0，当前迁移到 `0015 (head)`。
- AI：DeepSeek 仅由后端调用，支持 F12 需求解析和 F13 方案解释。
- 验证基线：58 项常规测试通过；启用真实 MySQL 回滚测试后 59 项通过；前端生产构建通过。

详细状态见 `docs/framework-status.md`，接口见 `docs/contracts/api-contract.md`。

## 2. 数据库共享策略

本仓库不提交 `.env`、MySQL 数据目录或 SQL dump。数据库通过迁移和数据生成器重建：

1. Alembic 迁移创建完整表结构。
2. `app.bootstrap` 创建项目数据库和管理员。
3. `app.demo_seed` 生成可重复的合成演示数据。

这样可以避免传递密码哈希、登录会话、密码重置记录和本机私密配置。

`demo_seed` 当前以 2026-11-09 作为固定演示周。它适合页面验收；继续开发新功能时，应创建新的排班周期，或在后续迭代中将种子周期参数化。

## 3. 首次配置

### 3.1 安装依赖

```powershell
conda env create -f environment.yml
conda activate schedule
cd frontend
npm.cmd ci
```

已有 Conda 环境时可使用：

```powershell
conda activate schedule
python -m pip install -r requirements-schedule.lock.txt
```

### 3.2 创建本地配置

在仓库根目录复制 `.env.example` 为 `.env`，然后填写：

- `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER` 和本机数据库密码。
- 不少于 32 字符的随机 `CSRF_SECRET`。
- 本地前端/后端端口对应的 `ALLOWED_ORIGINS`。
- 如需使用 F12/F13，再填写自己的 DeepSeek 密钥。其他功能不需要该密钥。

生成随机 CSRF 密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 只保存在本机，不提交、不截图、不通过聊天发送。

### 3.3 创建数据库与管理员

```powershell
conda activate schedule
cd backend
python -m app.bootstrap create-db
python -m alembic upgrade head
python -m app.bootstrap admin
```

管理员密码通过交互式隐藏输入设置，首次登录需要修改。不要使用共享默认密码。

### 3.4 生成合成演示数据

```powershell
cd backend
python -m app.demo_seed
```

脚本可重复执行，不覆盖已有发布版本。可重复运行后检查：

- 当前周期有已发布班表和草稿；
- 员工、技能、岗位、规则、偏好、请假、换班、通知与缺口数据可见；
- 管理员可进入 F01—F16 页面。

如果新环境没有员工登录账号，由管理员在“账号审核”或“创建员工账号”页面建立临时账号，并绑定演示员工档案。不要把本机原账号密码复制给其他开发者。

## 4. 启动

终端一：

```powershell
conda activate schedule
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端二：

```powershell
cd frontend
npm.cmd run dev
```

访问地址：

- 前端：`http://127.0.0.1:5174`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`
- 数据库就绪检查：`http://127.0.0.1:8000/api/ready`

## 5. AI 配置与成本边界

F12/F13 共用每日调用次数，但输出边界相互独立：

- 每位用户每日 30 次。
- 全系统每日 300 次。
- F12 单次最多 800 个输出 token。
- F13 单次最多 1600 个输出 token。
- 输入最多 2000 字符，超时 20 秒。

这些值可在本地 `.env` 调整，但不能把真实密钥提交到仓库。

## 6. 数据库变更

- 新增表或字段时创建新的 Alembic migration。
- `down_revision` 必须指向合并前的最新 head。
- 不修改或删除已执行迁移。
- 不直接改已发布班表内容；通过草稿、统一校验和发布事务生成新版本。
- 合并数据库改动后运行：

```powershell
cd backend
python -m alembic upgrade head
python -m pytest -q
```

## 7. 已知限制

- 当前为单门店、单 API 进程；通知消费者和部分求解任务仍在进程内运行。
- 尚未部署公网，未实现多实例限流、独立 worker 和生产监控。
- 跨周已发布上下文仍需继续完善。
- `demo_seed` 的演示周目前固定，后续可参数化。
- 默认测试跳过真实 MySQL；需要显式设置 `IDS_TEST_MYSQL=1`。
- Starlette/httpx 的测试客户端存在弃用提示，不影响当前测试结果。

## 8. 后续开发入口

优先按 `CONTRIBUTING.md` 建立分支。技术升级先在 `spike/...` 分支做最小验证，并保留当前基线标签。任何框架替换都不应绕过统一权限、版本、发布和数据库迁移约定。
