# 协作与分支约定

本项目以 `main` 作为稳定、可构建、可演示的基线。继续开发时使用短期分支和 Pull Request，不直接在 `main` 上重构。

## 分支

- `main`：课程交付与稳定集成分支，只接受已审查的合并。
- `feature/<topic>`：具体功能、缺陷修复或测试补充。
- `spike/<topic>`：技术方案验证，例如前端框架、后端框架或数据库方案替换。
- `release/<version>`：仅用于需要冻结验收的版本，非必须。

提交前先同步最新 `main`。不要改写已经共享的 `main` 历史，不强制推送共享分支。

## 提交与 PR

建议使用清晰的提交前缀：

```text
feat:      新功能
fix:       缺陷修复
refactor:  不改变外部行为的重构
test:      测试补充
docs:      文档
chore:     工具或依赖维护
```

PR 至少说明：

- 修改目的与范围。
- 是否改变接口、数据库、权限或发布事务。
- 已执行的测试与构建结果。
- 页面变化截图或操作路径。
- 兼容性、风险和回滚方式。

## 本地检查

后端：

```powershell
conda activate schedule
cd backend
python -m pytest -q
```

涉及真实数据库回滚时：

```powershell
$env:IDS_TEST_MYSQL="1"
python -m pytest -q
Remove-Item Env:IDS_TEST_MYSQL
```

前端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
```

## 数据库

- 不修改已经执行过的历史迁移。
- 每次表结构变化新增 Alembic migration。
- 合并后运行 `python -m alembic upgrade head`。
- 两个分支同时新增迁移时，先协调 `down_revision`，不要删除对方迁移。
- `python -m app.demo_seed` 必须保持可重复执行。
- 不提交 MySQL 数据目录、SQL dump 或任何账号凭据。

## 共享契约

以下边界发生变化时必须同步更新文档并单独审查：

- `/api/v1` 路径、统一响应和错误码。
- 登录、CSRF、会话与角色过滤。
- `expected_revision`、幂等键和并发冲突处理。
- 班表复制、统一校验、发布事务与 outbox。
- Alembic 迁移链和已发布班表不可变规则。
- F12/F13 的模型输入过滤、密钥和调用成本边界。

## 技术框架升级

更换前端、后端或数据库技术方案时：

1. 先在 Issue 或 PR 描述中说明动机、影响面和迁移方案。
2. 在 `spike/...` 分支完成可运行验证。
3. 保持现有 HTTP 契约和迁移数据结构，或提供兼容层。
4. 不同时重写前端、后端和数据库。
5. 分批合并，每一批都必须可启动、可测试、可回滚。

## 安全

- `.env`、真实密码、API 密钥、会话令牌不得提交。
- 临时密码只在本机展示，不写入文档、日志、截图或测试夹具。
- 演示数据必须是合成数据，不使用真实个人信息。
- 发现密钥误提交时，先撤销并轮换密钥，再处理 Git 历史。
