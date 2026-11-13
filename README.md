# 智能排班与动态调班系统

本地课程项目，当前已完成 F01—F16 的正式页面与业务接口，包含自动排班、动态调班、通知确认、统计导出、DeepSeek 自然语言需求解析和角色过滤的方案解释。

## 环境

- Conda `schedule`，Python 3.12；MySQL 8.0.45；本机 Node 26.5.1 / npm 11.17.0。
- 同学首次安装：项目根目录执行 `conda env create -f environment.yml`，然后 `cd frontend`、`npm.cmd ci`。
- 已有环境按 `python -m pip install -r requirements-schedule.lock.txt` 同步依赖。

## 本地配置

根目录 `.env` 为本地私有配置，不分享、不提交；`.env.example` 是可共享模板。本机初次生成了随机 CSRF_SECRET，本机 DB_PASSWORD 已由用户填写；其他机器请仅在本地填写 MySQL root 密码；含 # 或空格的密码建议使用单引号包裹。密码含引号时按 dotenv 语法转义。

F12/F13 使用服务端 DeepSeek 配置：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`。密钥只由后端读取，不进入前端、数据库、审计或日志。默认成本边界为每位用户每天 30 次、全系统每天 300 次、F12单次最多800个输出token、F13单次最多1600个输出token、单次输入最多2000个字符、超时20秒；对应变量均可在 `.env` 调整。

同学复制 `.env.example` 为 `.env`，自行填写数据库密码，并用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成其本地 CSRF_SECRET（不少于32字符）。

未配置数据库时，前端登录页与 `/api/health` 可用，业务接口明确返回配置未完成。系统不会自动改用 SQLite 或虚假登录。

## 初始化（新机器使用）

```powershell
conda env create -f environment.yml
conda activate schedule
cd backend
python -m app.bootstrap create-db
python -m alembic upgrade head
python -m app.bootstrap admin
python -m app.demo_seed
```

执行前先从 `.env.example` 创建本机 `.env` 并填写数据库密码和随机 CSRF 密钥。命令只创建约定的 `intelligent_dynamic_scheduling` 库，不新建 MySQL 账号。管理员密码通过隐藏输入设置，没有固定默认密码；第一次登录需修改。重复初始化不会覆盖已有账号。

仓库不包含任何管理员密码。每位开发者在本机创建自己的管理员账号和临时员工账号，不共享密码。若本机已存在 `INITIAL_ADMIN_PASSWORD`，它只属于该机器的本地配置，不得写入文档或提交。

可选：`python -m app.bootstrap demo` 添加明确以 DEMO 编号标识的员工档案，不创建默认密码账号。`python -m app.demo_seed` 生成 F01—F16 页面验收所需的完整合成资料、班表和事件；脚本可重复执行，不会覆盖已有发布版本。正常运行时应由账号本人提交找回密码申请，管理员登录后在“密码重置审批”页面核实并处理；`python -m app.bootstrap reset-password` 仅作为有本机访问权限时的受控兜底命令。

## 启动

终端一（后端目录，激活 schedule）：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端二（前端目录）：

```powershell
npm.cmd ci
npm.cmd run dev
```

页面 http://127.0.0.1:5174 ，API 文档 http://127.0.0.1:8000/api/docs 。`/api/health` 检查进程，`/api/ready` 检查真实数据库与表。前端通过 Vite 代理访问 API；变更访问端口时同步 `.env` 的 ALLOWED_ORIGINS。

前端缓存及 Vite 临时文件保存在项目 `.local-npm-cache` 和 `.local-build-temp`，不修改全局环境变量。

也可分别运行 scripts/dev-backend.ps1 和 scripts/dev-frontend.ps1；两者均在当前终端前台运行，不创建隐藏或持久服务。

## 检查

```powershell
# backend 中
python -m pytest -q
python -m alembic upgrade head --sql
# frontend 中
npm.cmd run build
```

默认测试跳过真实 MySQL 测试；在后端终端设置 `$env:IDS_TEST_MYSQL="1"` 后运行 pytest 可包含真实 MySQL 事务测试，结束后用 `Remove-Item Env:IDS_TEST_MYSQL` 清除开关。测试回滚临时数据并验证无残留。第二项只输出迁移 SQL。实际 MySQL 联调结果以 docs/framework-status.md 为准。

当前基线为 58 项常规测试通过；启用真实 MySQL 回滚测试后 59 项通过。

## 交接边界

当前已实现 F01—F16：账号权限、人员岗位技能、班次需求、可用时间与偏好、规则版本、自动求解、草稿调整与统一校验、发布/历史/差异、员工当前班表、请假申请审批、换班审批、动态调班、DeepSeek 自然语言需求解析、方案解释、通知与发布确认、统计与CSV导出、审计与基础设置。[实现状态](docs/framework-status.md)与[完整接口设计](docs/contracts/api-contract.md)分开维护。

## 文档

- [新环境搭建与交接](docs/handover.md)
- [协作与分支约定](CONTRIBUTING.md)
- [总体设计](docs/system-design.md)
- [页面设计](docs/ui-design.md)
- [数据库设计](docs/database-design.md)
- [合作方式](docs/collaboration.md)
- [开发计划](docs/development-plan.md)
- [技术基线](docs/technical-baseline.md)

本地 Git 基线由本项目维护，远程仓库地址和推送操作由用户确认后执行。提交前继续遵守 `.gitignore`，不得包含 `.env`、数据库导出、真实密码、API 密钥、依赖目录、构建产物和运行日志。
