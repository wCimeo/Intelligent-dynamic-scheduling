# F09—F16 联调与共享能力交接

更新：2026-11-09。F01—F16 已完成可运行闭环。本文定义共享能力、各模块联调边界和已验证状态，不提供伪造成功接口。

## 1. 责任边界

| 范围 | 本方（已完成） | 同学（待实现） |
|---|---|---|
| 账号与权限 | 登录、会话、角色、账号状态 | 无 |
| 人员资格 | 员工、岗位、技能、可胜任岗位 | 业务侧选择与展示 |
| 班次与规则 | 模板、周需求、规则版本 | 无 |
| 时间与偏好 | 常规时间、日期例外、偏好 | AI 解析、申请影响界面 |
| 求解与校验 | 输入快照、CP-SAT、统一硬软约束 | 动态调班策略、方案比较 |
| 版本与发布 | 草稿、发布、历史、差异、当前班表 | 业务审批后的调用 |
| 事件与审计 | 发布事件、核心审计事实 | 通知、确认、日志查询 |
| 统计与导出 | 当前发布版本及原始指标 | 统计口径、页面、CSV |

## 2. 服务级共享接口

同一后端模块应优先导入 `backend/app/shared.py`，不要在同学模块中重复实现查询和事件写入。

| 函数 | 用途 | 事务约定 |
|---|---|---|
| `current_published_version(session, period_id)` | 读取周期当前发布版本 | 只读 |
| `employee_published_assignments(session, employee_id, from, to)` | 员工当前发布安排 | 只读 |
| `outbox_events(session, after_id, state, limit)` | 消费领域事件 | 只读 |
| `acknowledge_outbox_event(session, event_id)` | 标记事件已处理 | 复用调用方事务 |
| `record_outbox_event(session, event_type, aggregate_id, payload)` | 业务事件入队 | 复用调用方事务，不自行提交 |
| `audit_events(session, ...)` | 查询审计事实 | 只读 |
| `approved_unavailability(session, employee_ids, from, to)` | F09 不可用时间适配点 | 只读，当前默认返回空列表 |

`validate_assignments(snapshot, assignments)` 与 `solve_snapshot(snapshot, limit)` 位于 `validation.py`、`solver.py`，供 F10/F11/F13 复用。

## 3. HTTP 联调接口

以下接口已实现，均要求管理员会话；后台消费者应在 Python 服务层调用，不应伪造管理员 Cookie。

| 方法与路径 | 返回 | 主要使用方 |
|---|---|---|
| `GET /api/v1/shared/capabilities` | 共享能力清单 | 联调自检 |
| `GET /api/v1/shared/periods/{id}/published-version` | 当前发布版本、班次、需求、安排、指标 | F09、F10、F11、F13、F15 |
| `GET /api/v1/shared/employees/{id}/schedule?from=&to=` | 员工当前发布安排 | F09、F10、F13、F15 |
| `GET /api/v1/shared/outbox-events?after_id=&state=` | 领域事件增量列表 | F14、F16 |
| `POST /api/v1/shared/outbox-events/{id}/ack` | 标记事件已处理 | F14 |
| `GET /api/v1/shared/audit-events?after_id=&entity_type=&entity_id=` | 审计事实增量列表 | F16 |

既有可复用接口：

- 员工资格、可用时间和偏好：`/employees/{id}`、`/employees/{id}/availability`、`/employees/{id}/preferences/{period_id}`。
- 版本上下文与校验：`/versions/{id}`、`/versions/{id}/eligible-employees`、`/versions/{id}/validate`。
- 发布与历史：`/versions/{id}/publish`、`/versions/{id}/copy-to-draft`、`/periods/{id}/versions`、`/versions/{id}/diff`。

## 4. 按模块联调

### F09 请假

1. 使用员工当前安排查询受影响班次。
2. 在同学模块自己的事务内批准请假并保存不可用区间。
3. 实现并替换 `approved_unavailability`，返回字段：`employee_id,work_date,start_time,end_time`。
4. 求解和统一校验会自动从有效可用窗口中扣除这些区间。

请假原因不得进入共享快照、发布事件或无关员工响应。

F09 已于 2026-11-08 接入：`backend/app/leave.py` 提供员工预览/提交/撤回、管理员筛选/审批、重叠检查、幂等审批和缺岗事件；`backend/app/shared.py` 的适配函数已读取 APPROVED 请假。前端 `/leave` 已从占位页替换为正式申请/审批页面。

### F10 换班（已实现）

1. 读取当前发布版本和员工资格。
2. 复制当前版本为新草稿。
3. 修改草稿安排后调用统一校验。
4. 发布新版本。

发布核心已抽取为 `publish_in_transaction`。F10 审批在同一事务中复制当前发布版本、应用转交/交换、执行统一校验、发布新版本并标记申请成功；不会只更新审批状态而不发布班表。

### F11 动态调班（已实现）

- 复用当前发布版本、员工资格、可用时间和统一快照构建。
- 复用 `solve_snapshot` 或在其输入模型上增加修复目标。
- 候选结果必须含基准版本和输入 revision；应用前重新校验。
- 最多展示 3 个不同方案，不能把同一结果重复包装成多方案。

当前`app/adjustment.py`和修复求解器已接入缺岗事件、锁定范围、候选比较和应用发布；正式页面为`/dynamic-adjustment`。

### F12 自然语言需求解析

- AI 只输出待确认结构，不直接写库。
- 用户确认后调用现有个人或管理员代录可用时间/偏好接口。
- 日期必须转换为具体 `YYYY-MM-DD`；模糊表达必须让用户确认。

已于2026-11-09实现：`backend/app/ai_service.py`通过服务端DeepSeek配置生成严格JSON，解析记录保存到`ai_parse_records`，只有所属员工确认后才在同一事务内写入日期例外和偏好草稿。确认请求仍执行日期范围、重复项、revision、员工状态、班次和周期校验。密钥不进入前端、数据库、审计或日志；默认用户每日30次、全局每日300次、单次输出800 tokens、输入2000字符、超时20秒。`/ai-requirements`已替换为正式页面，失败时回退`/availability`。

### F13 方案解释

- 输入只能使用发布版本、候选方案或统一校验返回的事实与指标。
- 员工仅接收本人可读信息；不得获得他人请假原因。
- 解释失败时使用固定模板。

已于2026-11-09实现：`/api/v1/ai/schedule-explanations`支持管理者解释当前发布班表或动态调班候选，员工仅解释本人当前发布安排。后端在调用模型前完成角色过滤；员工输入不包含其他员工姓名、班次或请假原因，候选解释仅管理者可用。模型失败时返回固定事实模板，状态为`FALLBACK`。解释记录保存已过滤事实和结构化输出，但只能由请求人读取；不提供应用候选或发布班表能力。

### F14 通知与确认（已实现）

- 消费 `schedule.published` outbox 事件，按 `event_key + recipient` 去重。
- 使用 `record_outbox_event` 在同一业务事务中记录事件，消费后再 ack。
- 发布核心事务不等待通知网络请求；发送失败可重试。
- 员工确认必须关联具体发布版本，不能确认已被替代版本。

当前`app/notifications.py`已实现outbox消费者、通知去重、通知列表/已读、发布回执和确认进度；正式页面为`/notifications`。通知失败最多重试3次，不影响已提交业务。

### F15 统计与导出（已实现）

- 只统计周期当前发布版本。
- 工时是计划工时，不表示实际出勤或薪资。
- CSV 必须处理公式注入字符并保持 UTF-8 中文可读。

当前`app/reports.py`提供全店/本人统计和三组CSV导出；正式页面为`/statistics`。

### F16 审计与设置（已实现）

- 通过 `audit_events` 增量读取核心审计事实。
- 设置修改不直接写入核心表；影响排班输入时改用共享服务和规则版本。
- 不在日志或事件中写密码、会话令牌和请假原因。

当前`app/settings.py`提供单门店设置、默认求解时限和审计筛选接口；正式页面为`/system-audit`，门店名称同步显示在侧栏。

## 5. 联调固定约定

- ID 在 JSON 中一律字符串，布尔值和数字保持 JSON 类型。
- 时间点使用带时区 ISO 8601；业务日期 `YYYY-MM-DD`，业务时间 `HH:mm`。
- 写操作沿用 `expected_revision`；发布、审批、任务创建沿用 `Idempotency-Key`。
- 不要直接修改 `schedule_versions`、`version_shifts`、`version_demands`、`assignments` 的已发布内容。
- 结构/外键错误必须拒绝；业务冲突可保存为草稿，但发布前必须全部修复。
- 新增同学表使用新 Alembic migration，不修改 F01—F08 的冻结历史迁移。
- 任何共享接口字段变更先更新本文与 `contracts/api-contract.md`，再改代码。

## 6. 联调顺序

1. 按 README 启动并运行现有 58 项常规测试；开启真实 MySQL 开关后为 59 项。
2. 先联调只读：当前发布版本、员工安排、资格/可用时间。
3. 再联调写入：偏好代录、候选校验、草稿复制。
4. F14 联调 outbox 增量读取与幂等 ack。
5. F09/F10 进入写事务联调前，共同审查“申请状态 + 班表发布”的原子事务入口。
6. 每个同学模块提供：正常样例、权限拒绝、版本冲突、重复请求、失败回滚和 MySQL 验证记录。

具体模块顺序、目录结构、开工前置和合并检查见 [F09—F16 开发与联调计划](f09-f16-development-plan.md)。
