# 智能排班与动态调班系统：同学开发交接说明

更新：2026-11-13  
当前基线：`v1.0-f01-f16-course-baseline`  
后端迁移：`0015 (head)`

## 1. 项目现状

当前已完成 F01—F16 的课程 Demo：

- 账号、审核、密码重置和权限控制。
- 员工、岗位、技能和人员资格。
- 班次模板、岗位需求、规则版本。
- 员工可用时间、日期例外和个人偏好。
- CP-SAT 自动排班、统一冲突校验和班表工作台。
- 发布、历史版本、差异比较和员工当前班表。
- 请假、换班和动态调班。
- 站内通知、发布确认、统计和 CSV 导出。
- 操作记录、门店设置和演示数据生成。
- F12 自然语言需求解析和 F13 方案解释。

当前验证基线：

- 后端常规测试：`58 passed, 1 skipped`。
- 开启真实 MySQL 回滚测试：`59 passed`。
- 前端 TypeScript 检查和生产构建通过。
- 构建仍有 Element Plus 单包体积提示，不影响当前运行。

详细功能状态见 `docs/framework-status.md`，接口字段以 `docs/contracts/api-contract.md` 和 `/api/openapi.json` 为准。

## 2. 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Element Plus、Vite |
| 后端 | Python 3.12、FastAPI、SQLAlchemy |
| 数据库 | MySQL 8.0、Alembic |
| 排班求解 | OR-Tools CP-SAT |
| AI | DeepSeek，仅由后端调用 |
| 测试 | pytest、SQLite 流程测试、真实 MySQL 回滚测试 |

## 3. 仓库协作方式

### 3.1 远程角色

- Gitee `main`：团队协作主线，同学从该仓库克隆和推送。
- GitHub `main`：仓库维护者的个人镜像和备份，不作为同学日常协作主线。
- 本地仓库由维护者连接 GitHub，并在 Gitee 有更新时手动同步镜像。

同学本地只需要 Gitee：

```powershell
git clone https://gitee.com/cimeo/Intelligent-dynamic-scheduling.git
cd Intelligent-dynamic-scheduling
```

### 3.2 当前协作模式

当前约定允许团队成员作为 Gitee 管理者协作，但为了避免覆盖，必须遵守：

1. 每次开始开发前先拉取最新 `main`。
2. 推送前再次拉取并解决冲突。
3. 不向 `main` 强制推送。
4. 不删除 `main`。
5. 不同时修改同一数据库迁移或同一发布事务。
6. 大型框架升级必须新建 `spike/...` 或 `feature/...` 分支，验证后再合并。

日常同步：

```powershell
git switch main
git pull --ff-only origin main
```

提交前：

```powershell
git fetch origin
git log --oneline --graph --decorate --all -20
git pull --rebase origin main
```

解决冲突、完成测试后再推送：

```powershell
git push origin main
```

如果推送被拒绝，说明远程已有新提交。禁止直接强制推送，应重新拉取、合并、测试再推。

### 3.3 分支建议

- 常规小修复：可按团队约定直接提交 `main`。
- 新功能：使用 `feature/<topic>`。
- 技术框架替换：使用 `spike/<topic>`。
- 数据库大改或前后端同时重构：必须单独分支并分批合并。

## 4. 首次环境配置

### 4.1 安装依赖

```powershell
conda env create -f environment.yml
conda activate schedule

cd frontend
npm.cmd ci
cd ..
```

已有 Conda 环境时：

```powershell
conda activate schedule
python -m pip install -r requirements-schedule.lock.txt
```

### 4.2 创建本地 `.env`

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将输出写入 `.env` 的 `CSRF_SECRET`，并填写自己的 MySQL 配置。

必须注意：

- `.env` 只保存在本机。
- 不通过聊天、截图、文档或提交共享真实密码和 API 密钥。
- DeepSeek 密钥可以不填，除 F12/F13 外的功能仍可正常使用。
- 不建议把个人访问令牌直接写进 Git remote URL。

### 4.3 重建数据库

本项目不共享 MySQL 数据目录或 SQL dump。表结构由迁移维护，演示数据由生成器创建：

```powershell
cd backend
python -m app.bootstrap create-db
python -m alembic upgrade head
python -m app.bootstrap admin
python -m app.demo_seed
```

`demo_seed` 说明：

- 使用合成数据，可以重复执行。
- 不覆盖已有发布版本。
- 当前固定以 `2026-11-09` 作为演示周，适合页面验收。
- 继续开发当前业务时，建议创建新的排班周期，或后续把种子周期参数化。

### 4.4 创建员工测试账号

本机管理员账号由 `bootstrap admin` 交互创建，仓库中没有共享密码。

员工测试账号建议：

1. 管理员登录。
2. 在“创建员工账号”中选择未绑定的演示员工。
3. 使用系统生成的一次性临时密码首次登录。
4. 首次登录立即修改为自己的本地测试密码。

不要复用仓库维护者本机的原账号密码。

## 5. 启动项目

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

地址：

- 前端：`http://127.0.0.1:5174`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`
- 数据库就绪检查：`http://127.0.0.1:8000/api/ready`

## 6. 目录说明

```text
backend/
  app/
    main.py             核心账号、员工、排班、发布和共享路由
    ai_service.py       F12/F13 模型适配与 AI 路由
    leave.py            请假申请与审批
    swap.py             换班申请与审批
    adjustment.py       动态调班与候选方案
    notifications.py    通知和发布确认
    reports.py          统计与 CSV 导出
    settings.py         设置与审计
    shared.py           共享查询和 outbox
    solver.py           CP-SAT 求解
    validation.py       统一硬软约束校验
  migrations/           Alembic 迁移，只追加，不改历史
  tests/                SQLite 流程测试与 MySQL 回滚测试

frontend/
  src/views/            登录、工作空间总页面
  src/components/       请假、换班、通知、调班、统计、AI 页面
  src/api.ts            统一请求、CSRF 和错误封装

docs/
  framework-status.md   当前真实完成状态
  contracts/            API 契约
  database-design.md    数据库设计
  system-design.md      总体设计
```

## 7. 开发前必须理解的约束

### 7.1 身份和权限

- 角色、用户 ID 和员工绑定关系只从服务端会话读取。
- 不信任前端传入的 `role`、`user_id` 或 `employee_id` 作为授权依据。
- 员工查询必须只返回本人可读数据。
- 管理员接口和员工接口不能混用权限。

### 7.2 写请求

- POST、PUT、PATCH、DELETE 必须经过 CSRF 和 Origin 校验。
- 可变对象使用 `expected_revision` 防止覆盖并发修改。
- 发布、审批和任务创建使用 `Idempotency-Key`。
- 冲突应返回 409，不应静默覆盖。

### 7.3 班表发布

- 已发布班表不可原地修改。
- 修改安排必须复制为草稿、重新执行统一校验，再生成新发布版本。
- 请假、换班和动态调班必须复用统一发布事务。
- 已经开始或结束的班次不能通过新版本改写。
- 不要为 F09—F16 新建另一套发布逻辑。

### 7.4 数据库迁移

- 迁移文件位于 `backend/migrations/versions/`。
- 不修改已经执行过的历史迁移。
- 每次表结构变化新增 migration。
- 两个人同时新增迁移时，合并前协调 `down_revision`。
- 合并数据库改动后运行：

```powershell
cd backend
python -m alembic upgrade head
```

### 7.5 AI

- 密钥只由后端读取，不进入前端、数据库、审计或日志。
- F12 结果必须由员工确认后才能写入可用时间或偏好。
- F13 员工解释只能读取本人数据，不包含其他员工安排或请假原因。
- 候选方案解释不能声称已经证明全局最优。
- 模型失败时必须回退固定模板，不伪造成功。

## 8. 测试与提交前检查

后端：

```powershell
conda activate schedule
cd backend
python -m pytest -q
```

预期：

```text
58 passed, 1 skipped
```

真实 MySQL：

```powershell
$env:IDS_TEST_MYSQL="1"
python -m pytest -q
Remove-Item Env:IDS_TEST_MYSQL
```

预期：

```text
59 passed
```

前端：

```powershell
cd frontend
npm.cmd run build
```

提交前至少检查：

- [ ] 后端测试通过
- [ ] 前端构建通过
- [ ] 新增迁移可以从当前 head 升级
- [ ] 没有提交 `.env`、密码、密钥或数据库 dump
- [ ] 没有直接修改历史迁移
- [ ] 没有绕过统一校验或发布事务
- [ ] UI 已有实际操作路径或截图
- [ ] 文档和 API 契约已同步

## 9. CI 说明

仓库中的 `.github/workflows/ci.yml` 只会在 GitHub 上执行：

- 后端 pytest。
- 前端 `npm ci` 和构建。

Gitee 不会自动执行 GitHub Actions。因此在 Gitee 直接协作时，推送前必须在本机完成上述测试。若要使用强制状态检查，需要在 Gitee Go 中另建流水线。

## 10. 框架或技术方案升级

允许升级，但不要直接在共享 `main` 一次性替换整个技术栈。

推荐步骤：

1. 先写清楚升级目标、影响范围、迁移和回滚方案。
2. 新建 `spike/<topic>` 分支。
3. 先做最小可运行验证。
4. 保持 `/api/v1` 契约和数据库迁移兼容，或提供适配层。
5. 前端、后端和数据库不要同时大改。
6. 每完成一个可运行阶段就测试并合并。
7. 合并前保留当前基线标签，确保可以回到旧版本。

## 11. 已知限制

- 当前是单门店、单 API 进程。
- 通知消费者和部分求解任务仍在进程内运行。
- 尚未拆分独立 worker。
- 跨周已发布上下文仍需完善。
- 多实例限流、生产部署、监控和备份尚未实现。
- `demo_seed` 的演示周目前固定。
- pytest 存在 Starlette/httpx 测试客户端弃用提示，不影响当前通过结果。

## 12. 交接验收

同学本地首次完成以下步骤后，即可认为交接成功：

1. Gitee 克隆成功。
2. `.env` 和 MySQL 配置完成。
3. Alembic 升级到 `0015`。
4. `demo_seed` 执行成功。
5. 管理员和员工测试账号可以登录。
6. 前端和后端可以启动。
7. 后端 `58 passed, 1 skipped`。
8. 真实 MySQL 开启后 `59 passed`。
9. 前端 `npm.cmd run build` 通过。
10. 可以向 Gitee `main` 推送一个不含敏感文件的小提交。

## 13. 关键文档

- `README.md`
- `CONTRIBUTING.md`
- `docs/handover.md`
- `docs/framework-status.md`
- `docs/contracts/api-contract.md`
- `docs/database-design.md`
- `docs/system-design.md`
