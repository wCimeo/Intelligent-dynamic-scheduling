# 接口契约（审查稿 V1）

日期：2026-11-09。F01—F16的账号、人员岗位技能、班次需求、可用时间/偏好、规则版本、自动求解、班表工作台、发布版本、请假、换班、动态调班、自然语言需求解析、方案解释、通知确认、统计导出、审计设置接口已经实现并通过流程测试。字段如与当前 OpenAPI 不一致，应先更新契约再改实现。

## 1. 通用规范

前缀 /api/v1。JSON 字段 snake_case；ID 字符串；日期 YYYY-MM-DD；业务时间 HH:mm；时间点 ISO 8601 带时区。用户可见 message 为中文，code 为稳定英文标识。

响应统一：

```json
{"code":"OK","message":"操作成功","data":{},"trace_id":"request-id"}
```

列表 data 为 {items,total,page,page_size}，默认 page=1、page_size=20，上限100。排序字段白名单化。

错误响应包含 code、中文 message、data.errors（字段或冲突详情）、trace_id。HTTP 400 非法操作、401 未登录、403 无权限、404 不存在或不允许暴露的对象、409 状态/版本/唯一性冲突、422 字段错误、429 限流、503 依赖暂不可用。不得返回 HTTP 200 伪装失败。

例：409 VERSION_CONFLICT，“班表已更新，请刷新后重试”；422 VALIDATION_FAILED，“结束时间必须晚于开始时间”。缺少凭据或认证失败不返回密码相关细节。

成功创建资源返回201；创建异步任务返回202；其他成功返回200。POST 登录和注册仍需限频。

## 2. 身份与并发

设计采用服务端随机会话，浏览器 HttpOnly Cookie 保存令牌；服务端只保存哈希。部署 HTTPS 下启用 Secure，SameSite=Lax，生产前端与 API 同站部署；本地由 Vite 代理 /api。写接口校验 Origin，并使用 CSRF 令牌，所有凭据使用禁止缓存响应。

登录刷新会话令牌；退出、密码更改、重置及停用均服务端撤销。受限会话只能查询审核状态或修改临时密码，不能调用业务接口。业务角色从会话取，不信任客户端 role/user_id。

可变对象提交 expected_revision，成功响应包含新 revision；版本不匹配返回409。发布同时携带草稿 revision、基准已发布版本和期望周期 revision。任务创建、发布、审核、重置使用 Idempotency-Key；同一账号同一操作同一键不同请求返回409，同请求重试返回原结果。临时密码明文例外：不持久化响应明文，重复请求只返回已执行状态，不再次返回原临时密码。

## 3. 账号 F01

| 方法与路径 | 输入 | 输出与权限 |
|---|---|---|
| GET /auth/csrf | 无 | CSRF token；允许匿名，仅用于后续写请求防护 |
| POST /auth/register | username, name, password, password_confirmation | user_id,status=PENDING；服务端固定员工角色 |
| POST /auth/login | username,password | user{id,name,role,status},session_scope,must_change_password；通过 Cookie 建立会话 |
| GET /auth/me | 无 | 当前身份及允许访问范围；密码字段永不返回 |
| POST /auth/logout | 无 | 撤销当前会话 |
| POST /auth/change-password | old_password,new_password,confirmation | 修改并撤销旧会话，要求重新登录；允许 PASSWORD_CHANGE 会话 |
| POST /auth/password-reset-requests | username | 无论账号存在与否都返回同一受理提示 |
| GET /admin/accounts | status,page,page_size | 管理者查看账号和待审核列表 |
| POST /admin/accounts | username,name,employee_id? | 管理者建员工账号；临时密码单次显示、强制修改 |
| POST /admin/accounts/{id}/review | decision,expected_revision,employee_id? 或 new_employee{employee_no,name,weekly_limit_minutes,employment_type},note? | 管理者批准或拒绝；批准时创建/绑定档案 |
| PATCH /admin/accounts/{id}/status | status,expected_revision | 管理者停用/启用；最后管理员保护 |
| GET /admin/password-reset-requests | status | 管理者查看待处理项，不含任何密码 |
| POST /admin/accounts/{id}/reset-password | request_id?,expected_revision,verification_note | 线下核实后重置，返回 temporary_password,expires_at 一次；撤销旧会话 |

拒绝重复绑定已有账号的员工档案；待审核与员工停用状态不能通过登录接口升级。注册账号冲突返回409 ACCOUNT_UNAVAILABLE。

2026-11-08 实现说明：重置申请支持 PENDING、PROCESSED、REJECTED 状态；管理员列表可按状态筛选并分页。重置请求要求 Idempotency-Key、expected_revision 和身份核实说明；成功后版本递增、全部旧会话撤销、临时密码24小时有效，重复键只返回已处理状态。管理员可直接创建已启用员工账号并可选绑定未使用员工档案，创建使用幂等键且临时密码只显示一次；账号列表支持状态筛选，停用/启用要求最新 revision，停用时撤销全部旧会话，并禁止停用最后一个有效管理员。F01 的账号管理页面与接口已补齐；员工岗位技能、个人班次和申请记录按 F02、F04、F09 依赖阶段继续实现。

## 4. 人员、岗位、技能 F02

| 方法与路径 | 输入/输出 | 权限 |
|---|---|---|
| GET/POST /employees | 筛选或创建 {employee_no,name,weekly_limit_minutes,employment_type} | 管理者 |
| GET/PATCH /employees/{id} | 详情或部分字段 + expected_revision | 管理者；员工用 /me/profile |
| GET /me/profile | 本人员工信息及岗位技能 | 员工 |
| PUT /employees/{id}/skills | skill_ids,expected_revision；整体替换 | 管理者 |
| PATCH /employees/{id}/status | ACTIVE/INACTIVE,expected_revision | 管理者；返回受影响未来安排摘要 |
| GET/POST /skills，GET/POST /positions | code,name；创建/查询字典 | 管理者写；员工读取有效字典 |
| PATCH /skills/{id}，PATCH /positions/{id} | name,active,expected_revision | 管理者 |
| PUT /positions/{id}/skills | skill_ids,expected_revision | 管理者，要求全部技能 |

返回实体字段与数据库设计一致，但隐藏 user_id 等无关关联和账户秘密。更新技能后递增输入 revision；已有发布安排失效时显示异常待处理，不自动抹去历史。

2026-11-08 实现说明：员工列表支持姓名/编号搜索、在岗状态和无重复技能满足指定岗位的资格筛选；员工详情包含技能及当前可胜任岗位。员工资料更新、员工技能整体替换和状态切换均校验 expected_revision。岗位与技能使用编码唯一、名称可编辑、状态停用替代删除；岗位所需技能采用整体替换，员工必须同时具备全部要求。当前尚无排班表，员工停用返回的未来安排影响数为0并保留该字段，F03/F06 接入后再返回真实影响摘要。

## 5. 班次和需求 F03

| 方法与路径 | 输入与结果 |
|---|---|
| GET/POST /shift-templates | 列表/创建 {code,name,start_time,end_time,demands:[{position_id,required_count}]} |
| PATCH /shift-templates/{id} | 修改模板 + expected_revision，不改变历史班次 |
| POST /periods | {week_start}，必须周一；创建周期，重复返回409 |
| GET /periods | 日期范围筛选 |
| GET /periods/{id} | current_version_id,revision,execution_status；管理者 |
| POST /periods/{id}/drafts | {source_version_id?,source_period_id?}，空来源按模板生成；跨周复制按星期平移日期、生成本周期班次键 |
| PUT /versions/{id}/shifts | {expected_revision,shifts:[{shift_key?,template_id?,date,name,start_time,end_time,enabled,demands:[{position_id,required_count}]}]}；仅草稿，整体更新 |
| GET /versions/{id} | 读取完整草稿班次、岗位需求与指标；管理者 |

所有写操作为管理者；编辑已发布内容先创建草稿。复制本周期版本保留 shift_key；跨周期复制生成新 key。对当前周已开始部分必须继承当前发布内容，不允许任意删除。

2026-11-08 实现说明：班次模板保存默认岗位人数快照；修改模板不会改写已生成草稿。排班周期必须从周一开始，草稿按7天生成完整班次和岗位名称/人数快照。跨周复制按7天平移日期并生成新 shift_key，关闭班次和日期级岗位人数通过整体更新草稿实现。指标只统计启用班次，包含启用班次数、岗位需求数和需求工时。当前阶段 `current_version_id`、求解任务和发布状态尚未接入，由 F06/F08 完成。

## 6. 时间、偏好 F04 与规则 F05

| 方法与路径 | 输入/输出 |
|---|---|
| GET /me/availability | from,to；有效窗口及来源 |
| PUT /me/availability/weekly | expected_revision,effective_from,windows:[{weekday,start_time,end_time}]；按版本更新未来周期 |
| PUT /me/availability/overrides/{date} | expected_revision,mode,windows:[{start_time,end_time}]；首次新增 expected_revision=0 |
| DELETE /me/availability/overrides/{date} | expected_revision；删除未生效例外，不删除历史快照 |
| GET/PUT /me/preferences/{period_id} | 读取/整体保存 {expected_revision,items:[{date,template_id,kind,weight}],submit}；空 items 可表示无偏好 |
| GET /employees/{id}/availability | from,to；管理者读取 |
| PUT /employees/{id}/availability/weekly | 与本人接口同结构，管理者代录附 reason |
| PUT/DELETE /employees/{id}/availability/overrides/{date} | 与本人接口同结构，管理者代录附 reason |
| GET/PUT /employees/{id}/preferences/{period_id} | 管理者代录同结构，附 reason |
| GET /periods/{id}/submission-status | 员工填报状态，管理者 |
| GET/POST /rule-versions | 查询/新增 {effective_week,daily_shift_limit,weekly_minutes_limit,consecutive_days_limit,min_rest_minutes,weights}；只允许管理者写 |
| GET /rule-versions/{id} | 版本详情；员工仅返回可公开规则描述 |

员工 ID 始终来自当前身份；管理员代录统一审计。AI 解析由同学负责，其确认结果调用相同服务，仍校验角色、时间和数据范围。

2026-11-08 实现说明：员工可维护从周一开始生效的常规时间版本，同日时段禁止重叠；新版本自动关闭上一版本。日期例外支持 REPLACE（空窗口表示全天不可用）与 BLOCK（至少一个扣除区间），接口会合并为逐日实际可用时间。偏好按排班周期整体保存，区分 NOT_SUBMITTED、DRAFT、SUBMITTED，日期必须属于该周，班次模板必须启用。管理员可查看员工可用时间和填报完成度，并通过带 reason 的受审计接口代录常规时间、日期例外和偏好。员工读取周期和班次选项使用只返回安全基础字段的 `/period-options` 与 `/shift-template-options`。

2026-11-08 规则实现说明：规则版本创建后不可修改，version_no 全局递增；生效周必须为周一。选择规则时按 effective_week 最新优先，同周存在多个版本时再按 version_no 选择最新。生成或复制排班草稿时绑定当时生效的规则版本，新规则不会回写旧草稿。管理员可读取版本历史和创建人；员工通过 `/rule-versions/effective?week=` 或版本详情只读取规则参数与权重，不读取创建人等管理字段。

## 7. 排班任务与工作台 F06—F07

POST /solver-tasks 输入：

```json
{"period_id":"1","draft_version_id":"10","expected_draft_revision":3,"base_published_version_id":null,"rule_version_id":"2","time_limit_seconds":30}
```

输出202：{task_id,state:"QUEUED",input_revision}。使用幂等键；固定输入快照，不在请求内等待求解。默认时间上限30秒，允许范围5—120秒。

| 方法与路径 | 输入与输出 |
|---|---|
| GET /solver-tasks/{id} | state,elapsed_seconds,result_available,stale,error_code?；管理者 |
| GET /solver-tasks/{id}/result | 求解状态、指标、冲突说明及结果引用；未完成返回409 TASK_NOT_READY |
| POST /solver-tasks/{id}/apply-to-draft | expected_draft_revision,expected_input_revision；结果写入草稿，输入或草稿已变化则409，不自动发布 |
| GET /versions/{id} | 版本、班次、需求、安排、必要指标与 revision；管理者 |
| PUT /versions/{id}/assignments | expected_revision,items:[{shift_key,employee_id,position_id,locked}]；草稿整体替换，允许保存业务冲突，结构/外键错误仍拒绝 |
| GET /versions/{id}/eligible-employees | shift_key,position_id；按当前草稿列出合格员工与排除原因，管理者 |
| POST /versions/{id}/validate | expected_revision；返回 valid,input_revision,hard_conflicts,soft_warnings,metrics |
| GET /me/schedules | from,to；仅本人当前有效发布安排，标记当前缺岗/请假状态 |

校验项结构：{rule_code,message,employee_id?,shift_key?,position_id?,date?,severity}。没有偏好时指标为 null 并显示“未提交偏好”，不伪造百分比。

2026-11-08 实现说明：当前实现 POST /solver-tasks 固定输入快照并在后台执行 CP-SAT，GET /solver-tasks/{id} 同时返回任务状态、问题列表、指标和成功安排；成功结果直接写入目标草稿并递增草稿 revision。求解硬约束包括员工/账号有效、岗位全部技能、班次完整落入可用时间、精确岗位人数、每日班次、周工时、时间重叠、班间休息和连续工作天数。软目标使用规则版本中的偏好、工时均衡和晚班均衡权重；晚班暂定义为结束时间不早于22:00。任务幂等、阻止同一草稿并发任务，草稿求解期间变化则标记 DRAFT_CHANGED。当前采用单 API 进程后台线程，独立工作进程、跨周已发布安排上下文及手工重新校验由后续阶段完善。

2026-11-08 F07 实现说明：GET /versions/{id} 返回全部 shift_key、班次快照、岗位需求和人员安排；PUT /versions/{id}/assignments 整体替换草稿安排，结构、外键或“同一员工同一班次多岗位”错误直接拒绝，技能、可用时间、工时和覆盖等业务冲突允许保存。POST /versions/{id}/validate 返回硬冲突、偏好/公平软警告和覆盖/工时/偏好指标。锁定安排进入求解输入快照并作为硬条件保留，若员工不再满足技能或可用时间则报告 LOCKED_ASSIGNMENT_UNAVAILABLE。当前交互使用点击增删，不依赖拖拽；发布前最终强制校验由 F08 完成。

## 8. 发布与版本 F08

POST /versions/{id}/publish 输入：

```json
{"expected_draft_revision":4,"expected_period_revision":1,"base_published_version_id":null,"expected_input_revision":8}
```

返回 {version_id,version_no,published_at,period_revision,affected_employee_ids}。管理者权限，强制幂等键；事务内重新校验。示例数字仅用于说明契约，不是现存数据。

| 方法与路径 | 约定 |
|---|---|
| GET /periods/{id}/versions | 版本列表、状态、发布人及时间；管理者 |
| GET /versions/{id}/diff?other_version_id=... | 同周期差异：人员新增/移除/岗位变化、班次时间和需求变化；管理者 |
| POST /versions/{id}/copy-to-draft | expected_period_revision；历史恢复生成新草稿，已开始部分遵循当前发布版本 |
| POST /versions/{id}/discard | expected_revision；仅草稿可废弃 |

发布失败：409 VERSION_CONFLICT/INPUT_CHANGED；422 HARD_CONSTRAINT_VIOLATION；409 IMMUTABLE_SHIFT_CHANGED。保留原发布版本，禁止半成功。

2026-11-08 F08 实现说明：发布在 scheduling_guard、排班周期、草稿锁内执行，比较草稿 revision、周期 revision、当前基准发布版本和当前输入指纹，重新构建最新人员/技能/可用时间/偏好/规则快照并运行统一校验。硬冲突返回 422 和冲突列表；已经开始或结束的班次及安排必须与当前发布版本完全一致。成功后旧版本标记 SUPERSEDED、新版本标记 PUBLISHED、周期 current_version_id 指向新版本并递增 revision，同时写审计和 `schedule.published` outbox 事件。历史版本可复制为新草稿，已开始部分自动继承当前发布内容；草稿可废弃。员工通过 `/me/schedules` 只读取当前 PUBLISHED 版本中的本人安排。通知消费、已读确认和统计导出分别由 F14/F15 实现。

### 8.1 F09—F16 共享联调接口（已实现）

| 方法与路径 | 权限 | 返回或用途 |
|---|---|---|
| GET /shared/capabilities | 管理者 | 本方共享能力清单，用于联调自检 |
| GET /shared/periods/{id}/published-version | 管理者 | 当前发布版本、班次、需求、安排和指标 |
| GET /shared/employees/{id}/schedule?from=&to= | 管理者 | 指定员工当前发布安排 |
| GET /shared/outbox-events?after_id=&state=&limit= | 管理者 | 领域事件增量读取 |
| POST /shared/outbox-events/{id}/ack | 管理者 | 幂等标记事件已处理 |
| GET /shared/audit-events?after_id=&entity_type=&entity_id=&limit= | 管理者 | 核心审计事实增量读取 |

同一后端模块应直接复用 `app/shared.py`、`app/validation.py` 和 `app/solver.py`；HTTP 接口主要用于联调与前端适配。完整模块映射、事务边界和同学待实现范围见 `docs/f09-f16-integration.md`。

## 9. F09—F16 模块接口

F09 已实现，以下接口已从预留进入正式路由：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| POST `/me/leave-requests/preview` | 员工本人 | 预览时间范围内受影响的当前发布班次，不写库 |
| POST `/me/leave-requests` | 员工本人 | 提交待审批请假；幂等；阻止与待审批/已批准请假重叠 |
| GET `/me/leave-requests` | 员工本人 | 状态筛选，仅本人记录 |
| POST `/me/leave-requests/{id}/withdraw` | 员工本人 | 仅 PENDING 可撤回，校验 revision |
| GET `/leave-requests` | 管理者 | 按状态、日期、员工查询 |
| GET `/leave-requests/{id}` | 员工本人/管理者 | 员工只能读取本人记录 |
| POST `/leave-requests/{id}/review` | 管理者 | 批准或拒绝；拒绝必须填写说明；幂等 |

批准请假在 guard 事务中生成 `adjustment_events` 缺岗事实并递增输入 revision；`approved_unavailability` 会把每段已批准请假接入统一求解和校验，不修改已发布班表本身。批准且无替补时仍显示真实 OPEN 缺口。请假原因只返回本人和管理者。

F10 已实现：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET `/me/swap-candidates` | 员工本人 | 给定本人班次，返回可接收员工、排除原因和可用于交换的班次 |
| POST `/me/swap-requests` | 员工本人 | 发起转交或双向交换；拟议安排先过统一硬校验；幂等 |
| GET `/me/swap-requests` | 员工本人 | 本人发起或收到的换班申请 |
| POST `/me/swap-requests/{id}/respond` | 目标员工 | 接受或拒绝邀请，校验 revision |
| POST `/me/swap-requests/{id}/withdraw` | 发起员工 | 待接收人或待管理员阶段可撤回 |
| GET `/swap-requests` | 管理者 | 状态和员工筛选 |
| GET `/swap-requests/{id}` | 相关员工/管理者 | 相关员工只能查看自己参与的申请 |
| POST `/swap-requests/{id}/review` | 管理者 | 仅接收人确认后可审批；批准时复制当前版本、应用交换、统一校验并原子发布新版本 |

换班审批复用同一 `publish_in_transaction` 发布服务，不采用“先批准再独立发布”。基准版本变化、涉及班次已开始、员工资格或可用时间变化时申请失效；成功审批会幂等创建新版本并发布。双向交换的两个人员变化在同一事务中提交。

F14 已实现：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET `/me/notifications` | 当前用户 | 消息列表、未读筛选和未读数量 |
| POST `/me/notifications/{id}/read` | 当前用户 | 单条已读 |
| POST `/me/notifications/read-all` | 当前用户 | 全部已读 |
| GET `/me/publication-receipts` | 员工本人 | 当前及历史发布确认回执 |
| POST `/me/publication-receipts/{id}/confirm` | 员工本人 | 确认当前发布版本，校验revision，旧版本返回RECEIPT_OUTDATED |
| GET `/periods/{id}/confirmation-status` | 管理者 | 当前发布版本受影响员工确认进度 |
| POST `/notifications/process` | 管理者 | 手动触发outbox消费，用于联调和故障恢复 |

后台通知工作线程每2秒消费PENDING outbox，按`source_event_id + recipient_user_id`去重。`schedule.published`只通知受影响员工并创建确认回执；请假和换班事件通知对应员工/管理者。通知失败重试最多3次后标记FAILED，不撤销已成功业务；旧版本确认不能覆盖新版本。

F11 已实现：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET `/adjustment-events` | 管理者 | 按OPEN/RESOLVED和周期查询缺岗事件 |
| GET `/adjustment-events/{id}` | 管理者 | 缺口班次、岗位、原安排及基准版本 |
| POST `/adjustment-candidates/generate` | 管理者 | 对一个或多个同周期OPEN事件生成最多3个不同方案；支持锁定安排 |
| GET `/adjustment-events/{id}/candidates` | 管理者 | 查询事件候选方案 |
| POST `/adjustment-candidates/{id}/apply` | 管理者 | 重查基准版本和输入revision，应用方案、发布新版本并关闭缺岗 |
| POST `/adjustment-candidates/{id}/discard` | 管理者 | 弃用待选方案 |

修复求解复用原硬约束，目标先最小化与当前发布版本的变化人数/班次数，再优化偏好、工时和晚班均衡。候选保存完整安排快照、基准版本和输入revision；应用前重新校验，旧方案不能覆盖新版本。只展示实际找到的不同方案，不重复包装同一结果。

F15 已实现：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET `/statistics?period_id=&employee_id=&position_id=` | 管理者 | 当前发布版本的全店、员工和岗位统计 |
| GET `/me/statistics?period_id=` | 员工本人 | 本人计划工时、班次、晚班、偏好与确认 |
| GET `/exports/schedule.csv` | 管理者 | 当前发布班表CSV，可按员工/岗位筛选 |
| GET `/me/exports/schedule.csv` | 员工本人 | 本人当前发布班表CSV |
| GET `/exports/statistics.csv` | 管理者 | 员工统计CSV |

统计口径只使用周期当前PUBLISHED版本；计划工时不代表实际出勤或薪资。指标包含计划班次/工时、晚班、岗位数、偏好满足、OPEN缺岗、确认进度、换班和调班数量。CSV使用UTF-8 BOM、中文表头和RFC 5987文件名；单元格若以`= + - @`或控制字符开头会加单引号，防止电子表格公式注入。

F16 已实现：

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET `/settings/public` | 登录用户 | 门店名称、固定时区和演示模式 |
| GET `/settings` | 管理者 | 完整单门店设置及revision |
| PATCH `/settings` | 管理者 | 修改门店名称、演示模式、默认求解时限；expected_revision |
| GET `/audit-events` | 管理者 | 按类别、操作人、对象、日期和分页查询审计事实 |

门店时区固定为`Asia/Shanghai`。默认求解时限只在创建任务未显式提供时限时使用，不修改历史任务。审计查询使用现有事实表，不把密码、会话令牌或请假原因写入日志。设置修改记录修改前后摘要及操作者。

F12 已实现：

| 方法与路径 | 权限 | 输入与输出 |
|---|---|---|
| POST `/me/ai/availability/parse` | 在职员工本人 | `{text}`，1—2000字符；返回解析记录`id,status=PENDING_CONFIRMATION,revision,summary,overrides,preferences,clarifications,model,usage` |
| GET `/me/ai/availability/parses/{id}` | 记录所属员工 | 返回原文对应的结构化结果、状态、revision和模型用量；其他员工记录按不存在处理 |
| POST `/me/ai/availability/parses/{id}/confirm` | 记录所属员工 | `{expected_revision,overrides:[{date,mode,windows}],preferences:[{date,template_id,kind,weight}]}`；用户可修订模型结果；成功后写入日期例外和偏好DRAFT |
| POST `/me/ai/availability/parses/{id}/reject` | 记录所属员工 | `{expected_revision}`；只将解析记录标记REJECTED，不写可用时间或偏好 |

解析记录状态为 `PENDING_CONFIRMATION / CONFIRMED / REJECTED / FAILED`。解析阶段只保存待确认JSON和确认前业务revision快照，不直接修改F04业务表；确认阶段在一个事务内重新校验日期范围、时段重叠、重复项、员工状态、班次/周期和revision，再调用与手工表单相同的业务写入逻辑。

模型失败返回503及`AI_NOT_CONFIGURED / AI_UNAVAILABLE / AI_INVALID_RESPONSE / AI_HTTP_ERROR`，并带`fallback_url=/availability`；超出调用边界返回429 `AI_USER_LIMIT / AI_GLOBAL_LIMIT`。日期超出今天至未来90天、已变化输入、重复例外或重复偏好分别返回422/409，不产生半成功写入。

DeepSeek密钥只从后端环境读取。默认每位用户每日30次、全局每日300次、F12单次输出最多800 tokens、输入最多2000字符、超时20秒；临时HTTP错误和超时最多重试一次。

F13已实现：

| 方法与路径 | 权限 | 输入与输出 |
|---|---|---|
| POST `/ai/schedule-explanations` | 管理者或员工 | `{period_id,candidate_id?,question}`；管理者可解释当前发布班表或候选方案，员工只能解释本人当前发布班表 |
| GET `/ai/schedule-explanations?limit=20` | 当前用户 | 只返回当前用户发起过的解释记录，按时间倒序 |
| GET `/ai/schedule-explanations/{id}` | 当前请求人 | 记录详情；其他用户按不存在处理 |

解释输出结构为`{title,conclusion,reasons[],evidence[],limitations[]}`。记录状态为`IN_PROGRESS / COMPLETED / FALLBACK / FAILED`，服务成功时返回201和`COMPLETED`；模型超时、不可用或结构错误时仍返回201，但状态为`FALLBACK`，正文由后端固定事实模板生成，不伪造模型成功。

管理者当前班表事实包含版本、规则、计划工时、班次、晚班、岗位、偏好、确认和OPEN缺口；候选方案事实包含基准版本、变更人数/班次、指标、来源缺口及`optimality_proven=false`。员工请求由后端先过滤为本人班次、本人偏好和本人员工档案，不接受`candidate_id`，不得返回其他员工姓名、安排或请假原因。

F13默认`AI_EXPLANATION_MAX_OUTPUT_TOKENS=1600`，与F12的800输出token独立；每日用户/全局调用次数共享。解释只能读取事实，不提供应用候选、发布班表或替换统一校验的接口。

## 10. 内部公共服务契约

- load_scheduling_input(period_id,draft_id)：返回不可变人员、资格、可用时间、需求、规则、相邻周及 revision 快照。
- get_unavailability(employee_ids,date_range)：返回批准后不可用区间，不含请假原因；尚未接入时明确使用空适配器，并在联调文档标记限制。
- build_constraint_model(snapshot,locked_assignments)：创建公共硬约束模型；同学在其上增加动态调整目标。
- validate_schedule(snapshot,assignments)：返回固定结构的硬冲突、软警告、指标，不产生数据库副作用。
- publish_schedule(transaction,draft_id,expected_versions,actor,idempotency_key)：复用外层事务，不自行提前提交。
- record_domain_event(transaction,event_type,payload)：与发布同事务保存。事件包含 event_id、period_id、old/new_version_id、affected_employee_ids、actor_id、occurred_at，不含凭据或请假原因。

正式事件暂定 schedule.published、account.reviewed、account.password_reset（仅元数据）。后续通知消费者按 event_id + recipient 去重。账号密码不能经事件交付。

## 11. 审查及后续落地

接口设计从全中文页面动作反推，用户主要审查操作是否符合预期。F01—F16及共享联调层已生成对应路由、服务函数、Alembic迁移和流程测试。当前接口与错误码以本文件和 `/api/openapi.json` 的对齐结果为准。
