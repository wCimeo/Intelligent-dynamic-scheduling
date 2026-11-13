# 技术基线与本地环境核验

核验日期：2026-11-07。范围为环境准备、依赖兼容性与设计约定；未初始化应用，未实现业务，未进行仓库操作。

## 1. 基线选择

| 层次 | 选择 | 状态 |
|---|---|---|
| 前端 | Vue 3 + TypeScript + Element Plus，拟使用 Vite | 设计建议，未安装前端依赖、未锁定版本 |
| 前端工具 | Node.js 26.5.1、npm 11.17.0 | 本机版本已核验，待前端骨架阶段验证组合 |
| Python | Conda schedule，Python 3.12.16，Windows x64 | 已创建并验证 |
| Web 框架 | FastAPI 0.162.0、Uvicorn 0.54.0 | 已安装，框架内存测试通过；未启动业务服务 |
| 数据库 | MySQL 8.0.45，设计采用 InnoDB 和 utf8mb4 | 服务握手已核验，项目库尚未创建 |
| 数据访问 | SQLAlchemy 2.0.57、PyMySQL 1.2.3（rsa 依赖） | 安装及导入通过，数据库登录未验证 |
| 数据库迁移 | Alembic 1.20.1 | 安装及导入通过，未初始化迁移目录内容 |
| 配置 | pydantic-settings 2.16.2 | 安装及导入通过 |
| 排班求解 | OR-Tools 9.15.6755，CP-SAT | 最小求解返回 OPTIMAL |
| 测试 | pytest 9.2.0、HTTPX 0.28.1 | 安装及内存测试通过，见兼容性备注 |

Python 3.12 与 OR-Tools 的 Windows CPython 3.12 安装包兼容；本项目的实际安装与求解已验证。无需迁移至 PostgreSQL。Conda 负责解释器及基础运行库，pip 负责项目 Python 依赖；不复制 base 环境中的全部包。

当前环境路径：D:\Environment\miniconda3\envs\schedule。

## 2. MySQL 连接信息与验证边界

- 主机：localhost。
- 端口：3306。
- 用户提供的现有账号：root。
- 用户截图服务器版本与本机 TCP 握手版本：8.0.45。
- 已确认：服务可达、握手协议及版本正常。
- 未确认：账号认证、项目数据库访问权限、实际存储引擎与字符集配置。
- 未执行：登录尝试、SQL 查询、建库建表、授权变更或服务启停。

2026-11-07 用户确认：新建独立项目数据库 intelligent_dynamic_scheduling，使用现有 root 账号，不新建数据库账号。密码由用户填写在本地配置中，不写入文档或依赖文件。实际建库与认证尚未执行，不修改其他数据库或账号授权。数据库 root 与应用内管理员是不同身份，应用账号仍按账号流程设计。

## 3. 本次检查与结果

1. 沙箱内 Conda 曾出现 DLL 重定位错误，沙箱外查询成功；没有据此修复或重装 Conda。
2. 创建前存在 base 与 thesis；创建后新增 schedule。安装目标仅为 schedule，未向 base 或 thesis 安装项目依赖。
3. pip check 返回 No broken requirements found。
4. 核心模块导入成功。
5. CP-SAT 内存中求解一个布尔约束问题，返回 OPTIMAL，变量结果正确。这仅验证求解运行库，不代表项目排班算法已实现。
6. FastAPI TestClient 在内存中读取 OpenAPI 成功，没有启动监听服务或写入业务代码。
7. Asia/Shanghai 时区加载成功。
8. TCP 读取 MySQL 服务初始握手成功，没有发送登录信息。

兼容性备注：当前 Starlette 在使用 HTTPX 0.28.1 的 TestClient 时给出弃用提示，测试通过。进入测试框架设计时需核验其建议替代依赖或兼容版本组合，再统一更新锁定文件；本次未擅自扩大依赖安装范围。

## 4. 双人环境复现

项目根目录包含 environment.yml 与 requirements-schedule.lock.txt。后者记录实际安装的直接及传递 Python 依赖，是本次 Windows x64 验证快照，不代表已验证其他平台，也不替代 Conda 底层运行库的完整构建锁。

本机已经创建 schedule，只需使用：

```powershell
conda activate schedule
python --version
python -m pip check
```

同学首次创建时，在项目根目录执行以下命令；若已有同名环境，先确认用途，不直接覆盖：

```powershell
conda env create -f environment.yml
conda activate schedule
python -m pip check
```

VS Code 中通过 Python: Select Interpreter 选择 schedule。本机解释器路径为：

```text
D:\Environment\miniconda3\envs\schedule\python.exe
```

该路径是本机位置，不应硬编码进业务代码。同学使用其本机环境路径。激活环境后运行工具，不需要为本项目修改全局 PATH。

本期尚未安装登录加密等后续设计所需的全部依赖，也未安装 AI 模型 SDK；进入对应阶段时只按实际需要增加并同步版本快照。

## 5. 设计方案基线

- 前后端分离，后端为按业务模块组织的单体应用；初期不引入多业务微服务。
- API 服务与排班执行进程分开，任务状态与输入快照持久化到 MySQL，前端轮询状态。任务认领、超时、恢复与重复执行规则在详细设计中定义。
- CPU 密集的求解不占用 API 请求处理流程。求解时固定输入快照，应用结果时校验数据是否过期。
- 数据访问先采用同步 SQLAlchemy 与 PyMySQL，会话按请求或任务隔离；后台求解进程不共享连接与会话。
- 不依赖 PostgreSQL 专有约束实现冲突校验；采用 MySQL 外键、唯一约束、事务及统一业务规则校验。
- 发布、请假审批与换班相关操作需共享并发控制约定，覆盖跨周边界；具体锁定范围、顺序与版本字段在数据库详细设计阶段落实。
- 班表采用周期、版本和安排分层，发布历史不可原地改写。
- 用户与 AI 助手实现框架和 F01—F08；F09—F16 只提供必要接口契约和共享能力，具体实现由同学负责。

下一步为字段级数据字典、实体关系图、接口契约、状态机与页面结构设计，仍未进入应用编码。

## 6. 参考依据

- OR-Tools 发布文件：https://pypi.org/project/ortools/
- Python 3.12.16：https://www.python.org/downloads/release/python-31216/
- SQLAlchemy MySQL 驱动说明：https://docs.sqlalchemy.org/en/20/dialects/mysql.html

版本号和检查结果以本机本次实测为准。