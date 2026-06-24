# AstraTrade 架构文档

> 最后更新: 2026-06-24

## 目录

1. [项目概述](#1-项目概述)
2. [目录结构](#2-目录结构)
3. [核心架构与运行流程](#3-核心架构与运行流程)
4. [模块详解](#4-模块详解)
   - [4.1 Dashboard 层](#41-dashboard-层)
   - [4.2 Runtime 层](#42-runtime-层)
   - [4.3 Tool 层](#43-tool-层)
   - [4.4 Service 层](#44-service-层)
   - [4.5 Subagent 层](#45-subagent-层)
   - [4.6 System 层](#46-system-层)
   - [4.7 Skills 层](#47-skills-层)
   - [4.8 Workspace 持久层](#48-workspace-持久层)
5. [数据流详解](#5-数据流详解)
6. [配置系统](#6-配置系统)
7. [扩展点指南](#7-扩展点指南)
8. [安全架构](#8-安全架构)
9. [调试与监控](#9-调试与监控)
10. [常见修改场景](#10-常见修改场景)

---

## 1. 项目概述

AstraTrade 是一个**本地优先（local-first）的长期金融 Agent 运行时系统**，专为 A 股模拟交易研究设计。核心思想是：**Agent 不应依赖模型的隐式记忆来管理有状态金融工作**，而是通过持久化文件工作区存储完整状态，每次调用都从工作区重建上下文。

### 核心设计原则

1. **持久化工作区** — 所有状态（账户、市场、持仓、策略、事件、记忆）均以结构化文件存储
2. **协议约束循环** — Agent 输出必须遵循 `thinking → tool_call → final` 协议，确保可控性
3. **受限工具层** — 文件操作限定在工作区内，命令执行有白名单
4. **池模型** — 持仓、策略、候选池相互独立，便于审计和检查
5. **多模式运行** — 支持调度（scheduler）、人工（manual）、触发（trigger）三种唤醒模式
6. **分层子 Agent** — 持仓监控、候选监控、交易日记为独立进程，通过事件触发主 Agent

---

## 2. 目录结构

```
AstraTrade/
├── assets/                          # 图片资源（logo、架构图）
├── config/                          # 静态配置文件
│   ├── alarm.json                   # 闹钟/定时任务配置
│   ├── investment_style.json        # 投资风格配置
│   └── scheduler.json               # 调度器配置
│
├── dashboard/                       # 本地 Web 控制面板
│   ├── server.py                    # HTTP 服务器 (1842行)
│   ├── start.sh                     # 启动脚本
│   └── static/                      # 前端静态资源
│       ├── index.html               # 主页面
│       ├── app.js                   # 前端逻辑
│       └── styles.css               # 样式
│
├── runtime/                         # 核心运行时
│   ├── __init__.py
│   ├── launcher.py                  # 启动器（入口）
│   ├── agent.py                     # Scheduler 主循环
│   ├── agent_loop.py                # Agent 协议循环
│   ├── build_context.py             # 工作区上下文构建
│   ├── render_prompt.py             # Prompt 渲染
│   └── investment_style.py          # 投资风格处理
│
├── services/                        # 外部服务
│   ├── __init__.py
│   ├── llm_service.py               # OpenAI 兼容 LLM 调用
│   └── storage_service.py           # 存储辅助
│
├── subagent/                        # 子 Agent
│   ├── __init__.py
│   ├── holding_follow/              # 持仓监控
│   │   ├── exec_agent.py            # 执行入口
│   │   ├── holding_follow.py        # 核心逻辑
│   │   └── prompt.md                # 子 Agent 提示词
│   ├── candidate_follow/            # 候选股监控
│   │   ├── exec_agent.py
│   │   ├── candidate_follow.py
│   │   └── prompt.md
│   └── trading_diary/               # 交易日记
│       ├── exec_agent.py
│       └── prompt.md
│
├── system/                          # 系统提示词和规则
│   ├── core_prompt.md               # 核心系统提示词
│   ├── rules.md                     # 运行规则
│   ├── file_protocol.md             # 文件操作协议
│   ├── output_contract.md           # 输出协议
│   ├── tools.md                     # 工具定义
│   └── modes/                       # 模式提示词
│       ├── scheduler.md
│       ├── manual.md
│       └── trigger.md
│
├── tools/                           # Agent 工具层
│   ├── exec.py                      # 命令执行工具
│   ├── file_tools.py                # 文件操作工具
│   └── list_skills.py               # 技能列表
│
├── workspace/                       # 持久化工作区（.gitignore 部分排除）
│   ├── config/                      # 运行时配置
│   │   └── alarm.json               # 运行时闹钟配置
│   ├── state/                       # 状态文件（*.json 被 gitignore）
│   │   ├── account_state.json
│   │   └── market_state.json
│   ├── pools/                       # 池文件（*.jsonl 被 gitignore）
│   │   ├── holdings.jsonl
│   │   ├── strategies.jsonl
│   │   └── candidates.jsonl
│   ├── logs/                        # 日志（被 gitignore）
│   │   ├── trades.jsonl
│   │   ├── events.jsonl
│   │   ├── agent_runs.jsonl
│   │   ├── agent_runs/{run_id}/    # 单次运行详细记录
│   │   ├── scheduler/               # 调度器日志
│   │   └── mx_data/output/          # 数据查询输出
│   ├── memory/                      # 日记忆（被 gitignore）
│   │   └── {date}/
│   │       ├── summary.md
│   │       └── plan.md
│   ├── reports/                     # 运行报告（被 gitignore）
│   │   ├── {run_id}_prompt.md
│   │   └── {run_id}_result.json
│   ├── phases/                      # 市场阶段说明
│   │   ├── premarket.md
│   │   ├── intraday.md
│   │   └── postmarket.md
│   ├── skills/                      # Agent 技能
│   │   ├── mx-data/                 # 金融数据查询
│   │   ├── mx-search/               # 资讯搜索
│   │   ├── mx-moni/                 # 模拟交易
│   │   ├── stock-ranker/            # 股票排名
│   │   ├── astra-trade-schema/      # 工作区 Schema
│   │   ├── astra-trade-alarm/       # 闹钟管理
│   │   ├── skill-creator/           # 技能创建工具
│   │   └── tradingagents-analysis-0.6.2/  # 外部分析
│   ├── MARK.md                      # 市场关注
│   ├── STYLE.md                     # 投资风格说明
│   └── tmp/                         # 临时文件
│
├── .env.example                     # 环境变量模板
├── .gitignore
├── Makefile                         # 命令入口
├── initialization.sh               # 工作区初始化脚本
├── requirements.txt                 # Python 依赖
└── README.md
```

---

## 3. 核心架构与运行流程

### 3.1 总体架构

```
[Scheduler/ManualTask/TriggerEvent/Alarm]
                  │
                  ▼
         ┌────────────────┐
         │  Runtime        │
         │  Launcher       │  runtime/launcher.py
         └────┬───────────┘
              │
              ▼
         ┌────────────────┐
         │  Context        │
         │  Builder        │  runtime/build_context.py
         │  ────────────   │
         │  读取 workspace │
         └────┬───────────┘
              │
              ▼
         ┌────────────────┐
         │  Prompt         │
         │  Renderer       │  runtime/render_prompt.py
         └────┬───────────┘
              │
              ▼
    ┌─────────────────────────┐
    │  Agent Loop             │  runtime/agent_loop.py
    │  ────────────────────── │
    │  LLM ←→ Tool Layer     │
    │  ┌───────────────┐     │
    │  │ File Tools    │     │  tools/file_tools.py
    │  │ Exec Tool     │     │  tools/exec.py
    │  │ List Skills   │     │  tools/list_skills.py
    │  └───────────────┘     │
    └─────────────────────────┘
              │
              ▼
    ┌─────────────────────────┐
    │  Run Artifacts          │
    │  - prompt.md            │
    │  - result.json          │
    │  - step_*_{input,output,│
    │    tool_result}.json    │
    │  - agent_runs.jsonl     │
    └─────────────────────────┘
```

### 3.2 运行流程（一次完整调用）

```
1. Launcher (runtime/launcher.py)
   ├── 解析 CLI 参数（--mode, --task, --trigger-event 等）
   ├── 调用 build_context() 读取工作区状态
   ├── 调用 render_system_prompt() 组装提示词
   ├── 保存 prompt.md 到 reports/
   └── 调用 run_agent_loop()

2. Agent Loop (runtime/agent_loop.py)
   ├── for step in 1..max_steps:
   │   ├── call_llm() → 模型输出 JSON
   │   ├── parse_model_output() → 解析 JSON
   │   ├── assess_model_output_format() → 校验协议
   │   ├── 根据 type 分支：
   │   │   ├── "thinking" → 继续循环
   │   │   ├── "tool_call" → execute_tool_call() → 继续循环
   │   │   ├── "final" → 结束
   │   │   └── "error" → 重试
   │   ├── 保存 step_*_{input,output,tool_result}.json
   │   └── 消息累积到 messages[]
   └── save_run_summary() → run_summary.json

3. Tool 执行 (tools/file_tools.py + tools/exec.py)
   ├── 路径校验（必须在 workspace 内）
   ├── read / write / edit / add / write_memory
   └── exec（命令白名单校验 + 危险 Token 黑名单）
```

### 3.3 Agent 协议约束

模型输出必须遵循以下三种 JSON 格式之一：

**thinking**（思考阶段）:
```json
{"type": "thinking", "mode": "scheduler", "phase": "盘前", "knowns": {}, "unknowns": {}, "next_action": "..."}
```

**tool_call**（工具调用）:
```json
{"type": "tool_call", "tool": "read", "args": {"path": "state/account_state.json"}, "reason": "..."}
```

**final**（最终输出）:
```json
{"type": "final", "mode": "scheduler", "phase": "盘前", "summary": "...", "actions": [], "tool_calls": [], "decisions": [], "file_updates": [], "next_todos": []}
```

协议定义文件：`system/output_contract.md`

### 3.4 三种运行模式

| 模式 | 触发方式 | 用途 |
|------|---------|------|
| scheduler | 定时调度（config/scheduler.json） | 盘前检查、盘中监控、盘后复盘、晚间计划 |
| manual | 用户通过 CLI 或 Dashboard 输入 | 人工分析任务 |
| trigger | 子 Agent 事件、闹钟触发 | 持仓/候选股异动跟进 |

---

## 4. 模块详解

### 4.1 Dashboard 层

**位置**: `dashboard/server.py`（~1842 行）

基于 Python 标准库 `http.server.ThreadedHTTPServer` 实现，无外部 Web 框架依赖。

#### 核心类

```
DashboardState          → 全局状态（进程、锁、运行记录）
Handler(BaseHTTPRequestHandler) → HTTP 请求处理
```

#### API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 服务静态首页 |
| GET | `/static/*` | 静态资源 |
| GET | `/api/snapshot` | 完整工作区快照（账户、市场、持仓、策略、候选、配置、日志） |
| GET | `/api/style` | 投资风格配置 |
| GET | `/api/api-config` | API 配置（密钥脱敏显示） |
| GET | `/api/scheduler` | 调度器状态 |
| GET | `/api/scheduler-config` | 调度器配置 |
| GET | `/api/initialization` | 初始化状态 |
| GET | `/api/trace?run_id=...` | 运行轨迹详情 |
| POST | `/api/investment-style` | 保存投资风格 |
| POST | `/api/manual-run` | 提交人工任务 |
| POST | `/api/api-config` | 保存 API 配置到 .env |
| POST | `/api/scheduler-config` | 保存调度器配置 |
| POST | `/api/scheduler/start` | 启动调度器 |
| POST | `/api/scheduler/stop` | 停止调度器 |
| POST | `/api/initialize-workspace` | 初始化/重置工作区 |

#### 关键细节

- **进程管理**: Dashboard 管理 scheduler 和 manual run 子进程，使用 `subprocess.Popen`
- **状态读取**: 直接读取 workspace 中的文件，不经过 Agent
- **绑定地址**: 硬编码 `127.0.0.1`（仅本地访问），端口默认 8787
- **前段**: 纯原生 HTML + JS（无框架），通过 `fetch()` 调用 API

---

### 4.2 Runtime 层

#### 4.2.1 Launcher（`runtime/launcher.py`）

**入口点**，负责一次运行的完整生命周期：

```
1. 解析命令行参数
2. 确定运行模式（mode）
3. 调用 build_context() 加载工作区状态
4. 调用 render_system_prompt() 组装提示词
5. 调用 run_agent_loop() 执行 Agent 循环
6. 保存 result.json 和 agent_runs.jsonl
```

**参数**:
- `--mode`: scheduler / manual / trigger
- `--task`: manual 模式下的自然语言任务
- `--trigger-reason`: 触发原因
- `--trigger-event`: 触发事件（JSON 字符串或文件路径）
- `--max-steps`: 最大循环步数（默认 50）
- `--test`: 测试模式（日志写入 test/ 而非 workspace/）

#### 4.2.2 Agent Scheduler（`runtime/agent.py`）

**驻留进程**，周期性执行调度任务：

```
while True:
    1. 检查当前时间是否处于交易时段
    2. 检查是否到固定任务时间（盘前08:30、午间12:00、盘后15:30、晚间20:00）
    3. 运行子 Agent（持仓监控、候选监控）
    4. 调用 runtime.launcher --mode scheduler 执行主 Agent
    5. sleep(check_interval_seconds) 默认 30s
```

配置来源：`config/scheduler.json`

#### 4.2.3 Agent Loop（`runtime/agent_loop.py`）

**核心循环**，约 620 行。实现"模型→工具→模型"的受控协议循环：

```
主要状态：
- consecutive_thinking（连续 thinking 次数，超限强制要求行动）
- error_retry_count（连续错误次数，超限终止）

最大循环步数：max_steps（默认 10，Dashboard 任务默认 50）
最大连续 thinking：max_consecutive_thinking（默认 2）
最大错误重试：max_error_retries（默认 3）
```

**输出文件结构**（每个 step）：
```
workspace/logs/agent_runs/{run_id}/
├── step_001_input.json        → 本轮发送给 LLM 的 messages
├── step_001_output.json       → LLM 的原始输出及解析结果
├── step_001_tool_result.json  → 工具执行结果（仅 tool_call 步骤）
├── step_002_input.json
├── ...
├── run_summary.json           → 运行总结
└── agent_trace.json           → 完整追踪（可选）
```

#### 4.2.4 Context Builder（`runtime/build_context.py`）

**负责读取工作区文件**，构建运行时上下文（约 390 行）：

```python
RuntimeContext 包含：
- 当前时间/日期/星期/市场阶段
- 调用信息（mode, trigger_reason, user_task, trigger_event）
- account_state + market_state
- holdings_summary + strategies_summary + candidates_summary
- recent_trades + recent_events
```

**市场阶段检测逻辑**（`detect_market_phase()`）：
```
周末 → "非交易日"
09:30 前 → "盘前"
09:30~11:30 → "盘中"
11:30~13:00 → "午休"
13:00~15:00 → "盘中"
15:00 后 → "盘后"
```

#### 4.2.5 Prompt Renderer（`runtime/render_prompt.py`）

**组装最终发送给 LLM 的系统提示词**，按以下顺序拼接：

```
1. system/core_prompt.md（核心角色定义）
2. system/rules.md（运行规则）
3. system/file_protocol.md（文件操作协议）
4. system/output_contract.md（输出 JSON 格式协议）
5. system/tools.md（工具列表）
6. system/modes/{mode}.md（当前模式的专用指令）
7. workspace/MARKET.md（市场关注）
8. workspace/STYLE.md（投资风格说明）
9. build_context_markdown()（动态运行上下文）
10. workspace 中的 skills prompt
11. 附加指令（extra_instructions）
```

#### 4.2.6 Investment Style（`runtime/investment_style.py`）

投资风格管理系统，支持：
- 从 `config/investment_style.json` 读取配置
- 校验配置合法性
- 生成 `workspace/STYLE.md` 供 Agent 阅读
- 预定义风格库（`STYLE_LIBRARY`）包含：投资周期、风险偏好、选股方式、交易频率、决策依据、仓位风格、止盈止损、市场适应

---

### 4.3 Tool 层

#### 4.3.1 File Tools（`tools/file_tools.py`）

**工作区文件操作**，所有路径都经过 `_validate_path()` 安全检查（约 680 行）。

| 工具名 | 方法 | 功能 | 支持的文件类型 |
|--------|------|------|---------------|
| read | `read()` | 读取文件内容 | 任意（限 200KB） |
| write | `write()` | 写入/覆盖文件 | 任意（带 Schema 校验） |
| edit | `edit()` | 精确替换文本 | 任意（仅替换第一个匹配） |
| add | `add()` | 追加内容 | JSON（数组追加）、JSONL（行追加） |
| write_memory | `write_memory()` | 写入今日记忆 | summary.md / plan.md |

**安全机制**:
- `_validate_path()`: 确保解析后的绝对路径在 workspace 内
- `_validate_structured_file()`: 对 state/pools/logs 下的 JSON/JSONL 进行 Schema 校验
- 写入前快照，校验失败则回滚（`_snapshot_file()` + `_rollback_file()`）
- 使用临时文件 + `os.replace()` 实现原子写入

#### 4.3.2 Exec Tool（`tools/exec.py`）

**受限命令执行**（约 210 行）。

**白名单**（ALLOWED_BINARIES）:
```
ls, find, cat, sed, head, tail, pwd, python, python3, date, bash
```

**危险 Token 黑名单**（DANGEROUS_TOKENS）:
```
rm, sudo, curl, wget, ssh, scp, mv, chmod, chown, kill, pkill, nohup, screen, tmux, >, >>, |, &&, ;
```

**工作目录规则**:
- `.` → workspace/ 根目录
- `__project__` → 项目根目录
- `skills` → workspace/skills/
- 相对路径 → workspace/{相对路径}
- 绝对路径 → 允许（但不得超出项目根目录）

#### 4.3.3 List Skills（`tools/list_skills.py`）

返回 `workspace/skills/` 下已安装的技能列表及其描述。

---

### 4.4 Service 层

#### 4.4.1 LLM Service（`services/llm_service.py`）

OpenAI 兼容接口封装（约 120 行）：

```
配置加载：
- main 配置: LLM_API_KEY, LLM_URL, LLM_MODEL
- sub 配置: SUB_LLM_API_KEY, SUB_LLM_URL, SUB_LLM_MODEL（未设置则回退到 main）

特殊功能：
- <think>...</think> 标签支持（DeepSeek 风格思维链）
- extract_final_content(): 移除 think 块提取最终输出
- extract_think_content(): 提取 think 块内容用于日志

模型调用：
- temperature 默认 0.2
- 使用 openai>=1.0.0 SDK
```

#### 4.4.2 Storage Service（`services/storage_service.py`）

提供辅助的文件读写功能，用于 Dashboard 和 Runtime 共享。

---

### 4.5 Subagent 层

独立的子进程，周期性执行特定监控任务，通过 `trigger` 事件与主 Agent 通信。

#### 子 Agent 通信协议

子 Agent 通过向 `logs/events.jsonl` 写入事件记录来触发主 Agent：

```json
{
  "event_id": "hold_600519_20260624_001",
  "timestamp": "2026-06-24 10:30:00",
  "source": "holding_follow",
  "event_type": "holding_alert",
  "symbol": "600519",
  "trigger_type": "price_movement",
  "reason": "贵州茅台跌幅超过3%",
  "status": "pending",
  "run_id": ""
}
```

Scheduler 监测到新事件后，调用 `launcher --mode trigger --trigger-event {event}`。

#### 4.5.1 Holding Follow（`subagent/holding_follow/`）

**持仓监控子 Agent**:
- 检查当前持仓的价格变动、技术指标
- 发现异动时写入 events.jsonl
- 维护 `holding_state/` 目录用于记录自身状态

#### 4.5.2 Candidate Follow（`subagent/candidate_follow/`）

**候选股监控子 Agent**:
- 检查候选池中股票的触发条件
- 监控买入计划是否满足
- 发现符合条件时写入 events.jsonl

#### 4.5.3 Trading Diary（`subagent/trading_diary/`）

**交易日记生成子 Agent**:
- 每日定时生成交易日记
- 总结当日交易、持仓变动、市场观察

---

### 4.6 System 层

由 Markdown 文件组成，直接作为系统提示词的一部分发送给 LLM。

| 文件 | 用途 |
|------|------|
| `core_prompt.md` | Agent 核心身份定义（你是谁、你能做什么） |
| `rules.md` | 行为规则（不允许做什么、必须遵守什么） |
| `file_protocol.md` | JSON 文件的格式规范和写入约束 |
| `output_contract.md` | 输出 JSON 协议（thinking/tool_call/final 格式） |
| `tools.md` | 可用工具列表及参数说明 |
| `modes/scheduler.md` | 调度模式专用指示 |
| `modes/manual.md` | 人工任务模式专用指示 |
| `modes/trigger.md` | 触发模式专用指示 |

---

### 4.7 Skills 层

位于 `workspace/skills/` 下，每个 skill 为一个独立目录，通过 `SKILL.md` 和脚本文件提供能力。

| Skill | 功能 | 技术实现 |
|-------|------|---------|
| `mx-data` | 金融数据查询（行情、财务数据） | Python 脚本 + 妙想 API |
| `mx-search` | 资讯/研报搜索 | Python 脚本 + 妙想 API |
| `mx-moni` | 模拟组合管理（买入/卖出/查询） | Python 脚本 + 妙想 API |
| `stock-ranker` | 候选股排名 | Python 脚本 |
| `astra-trade-schema` | 工作区文件 Schema 定义 | Markdown 参考文档 |
| `astra-trade-alarm` | 自然语言闹钟管理 | Python 脚本 |
| `skill-creator` | 创建新 Skill | Python 脚本 |
| `tradingagents-analysis-0.6.2` | TradingAgents 外部分析 | Shell 脚本 + REST API |

**Skill 结构**:
```
{skill_name}/
├── SKILL.md           → 技能描述（Agent 阅读此文件了解如何使用）
├── _meta.json         → 元数据（ownerId 等）
├── scripts/           → 可执行脚本（可选）
└── references/        → 参考文档（可选）
```

---

### 4.8 Workspace 持久层

工作区根目录 `workspace/` 是系统的"数据库"。所有状态以文件形式持久化。

#### 状态文件（JSON）

**`state/account_state.json`**:
```json
{
  "mode": "initialization",
  "cash": 1000000,
  "total_asset": 1000000,
  "market_value": 0,
  "available_cash": 1000000,
  "position_count": 0,
  "risk": {
    "max_position_ratio": 1,
    "max_single_stock_ratio": 0.5,
    "max_daily_trades": 5,
    "stop_trading": false
  },
  "updated_at": "2026-06-24 10:00:00"
}
```

**`state/market_state.json`**:
```json
{
  "date": "2026-06-24",
  "market_view": "unknown",
  "risk_level": "unknown",
  "summary": "系统初始化，市场状态待更新。",
  "hot_topics": [],
  "watch_sectors": [],
  "avoid_sectors": [],
  "key_events": [],
  "updated_at": "2026-06-24 10:00:00",
  "evidence": []
}
```

#### 池文件（JSONL，每行一个 JSON 对象）

| 文件 | 行对象主要字段 |
|------|---------------|
| `holdings.jsonl` | holding_id, symbol, name, count, cost_price, current_price, market_value, unrealized_pnl, strategy_id, status |
| `strategies.jsonl` | strategy_id, symbol, name, strategy_type, status, entry_conditions, exit_conditions, stop_loss, position_plan |
| `candidates.jsonl` | candidate_id, symbol, name, score, status, trigger, buy_plan, risk |

#### 日志文件（JSONL）

| 文件 | 说明 |
|------|------|
| `trades.jsonl` | 模拟交易记录 |
| `events.jsonl` | 事件记录（子 Agent 触发、闹钟等） |
| `agent_runs.jsonl` | 主 Agent 每次运行的索引 |

#### 记忆文件

```
memory/{YYYY-MM-DD}/
├── summary.md    → 当日总结
└── plan.md       → 次日计划
```

#### 报告文件

```
reports/
├── {run_id}_prompt.md     → 该次运行的完整提示词
└── {run_id}_result.json   → 该次运行的最终结果
```

---

## 5. 数据流详解

### 5.1 调度器定时任务流

```
config/scheduler.json
        │
        ▼
runtime/agent.py (Scheduler 进程)
        │
        ├── 每 30s 轮询检查
        │   ├── 是否到固定任务时间？
        │   ├── 是否在交易时段内？
        │   └── 子 Agent 是否该执行？
        │
        ├── 执行子 Agent:
        │   subagent.holding_follow.exec_agent
        │   subagent.candidate_follow.exec_agent
        │   subagent.trading_diary.exec_agent
        │
        └── 执行主 Agent:
            runtime.launcher --mode scheduler
```

### 5.2 人工任务流

```
Dashboard Web UI / CLI (make manual TASK="...")
        │
        ▼
runtime/launcher.py --mode manual --task "xxx"
        │
        ├── build_context(workspace_dir, mode="manual", user_task="xxx")
        │   └── 读取: account_state.json, market_state.json, pools/*.jsonl, logs/*.jsonl
        │
        ├── render_system_prompt(mode="manual", user_task="xxx", ...)
        │   └── 拼接: core_prompt + rules + file_protocol + output_contract + tools + modes/manual.md + MARKET.md + STYLE.md + 运行上下文 + skills
        │
        ├── run_agent_loop(system_prompt, ...)
        │   └── 循环: LLM ↔ Tool Layer → 直到 final
        │
        ├── save prompt.md → reports/{run_id}_prompt.md
        ├── save result.json → reports/{run_id}_result.json
        └── append agent_runs.jsonl
```

### 5.3 触发事件流

```
子 Agent / 闹钟 / 外部系统
        │
        ├── 写入: logs/events.jsonl  {"event_id": "...", "source": "holding_follow", ...}
        │
        ▼
Scheduler 检测到待处理事件
        │
        ▼
runtime/launcher.py --mode trigger --trigger-event '{...}'
        │
        └── 与 manual 类似，但使用 modes/trigger.md 提示词 + 触发事件上下文
```

### 5.4 Tool Call 数据流

```
LLM 输出: {"type": "tool_call", "tool": "write", "args": {"path": "...", "content": "..."}}
        │
        ▼
agent_loop.py: execute_tool_call("write", args, project_root)
        │
        ├── FileTools.write(path, content)
        │   ├── _validate_path() — 安全检查
        │   ├── _snapshot_file() — 备份
        │   ├── 原子写入（临时文件 + os.replace）
        │   └── _validate_structured_file() — Schema 校验（失败则回滚）
        │
        ▼
工具结果返回给 Agent 循环
        │
        ▼
messages.append({"role": "user", "content": build_tool_result_message(result)})
        │
        ▼
继续循环 → LLM 获得工具结果后决定下一步
```

---

## 6. 配置系统

### 6.1 环境变量（.env）

| 变量 | 必需 | 用途 |
|------|------|------|
| `LLM_API_KEY` | 是 | 主 Agent 模型 API Key |
| `LLM_URL` | 是 | 模型端点 Base URL |
| `LLM_MODEL` | 是 | 模型名称 |
| `SUB_LLM_API_KEY` | 否 | 子 Agent API Key（未设置回退到 LLM_API_KEY） |
| `SUB_LLM_URL` | 否 | 子 Agent 端点 URL |
| `SUB_LLM_MODEL` | 否 | 子 Agent 模型名 |
| `MX_APIKEY` | 是 | 妙想服务 API Key |
| `MX_API_URL` | 是 | 妙想服务端点 |
| `TRADINGAGENTS_TOKEN` | 否 | 外部分析服务 Token |
| `TRADINGAGENTS_API_URL` | 否 | 外部分析服务地址 |
| `STOCK_AGENT_PYTHON` | 否 | Dashboard 启动子进程的 Python 路径 |

### 6.2 静态配置文件（config/）

| 文件 | 管理方式 | 说明 |
|------|---------|------|
| `config/scheduler.json` | Dashboard API / 直接编辑 | 定时任务、交易时段、子 Agent 配置 |
| `config/investment_style.json` | Dashboard API / 直接编辑 | 投资风格选项 |
| `config/alarm.json` | 运行时通过 Alarm Skill | 延迟/周期性闹钟任务 |

### 6.3 工作区运行时文件

| 文件 | 初始来源 | 管理方式 |
|------|---------|---------|
| `workspace/state/*.json` | `initialization.sh` 创建 | Agent 通过 write 工具更新 |
| `workspace/pools/*.jsonl` | `initialization.sh` 创建空文件 | Agent 通过 add/write 工具管理 |
| `workspace/logs/*.jsonl` | `initialization.sh` 创建空文件 | Agent 循环自动追加 |
| `workspace/memory/{date}/*.md` | Agent 运行时写入 | 通过 write_memory 工具创建 |
| `workspace/reports/*` | `launcher.py` 自动生成 | 每次运行自动创建 |

---

## 7. 扩展点指南

### 7.1 添加新的 Tool

1. 在 `tools/exec.py` 的 `ALLOWED_BINARIES` 中添加新二进制名（如果是外部命令）
2. 或直接在 `tools/file_tools.py` 中添加新方法
3. 在 `tools/file_tools.py` 或 `tools/` 下新建文件
4. 在 `system/tools.md` 中添加工具描述和参数格式
5. 在 `runtime/agent_loop.py` 的 `execute_tool_call()` 中添加路由

### 7.2 添加新的 Skill

1. 在 `workspace/skills/` 下创建 `{skill_name}/` 目录
2. 创建 `SKILL.md` 描述技能（Agent 通过 read 读取此文件）
3. 可选创建 `_meta.json`（元数据）
4. 可选创建 `scripts/` 目录（可执行脚本）
5. 可选创建 `references/` 目录（参考文档）
6. 在 `tools/list_skills.py` 中注册（如果需要）

### 7.3 添加新的 Subagent

1. 在 `subagent/` 下创建 `{subagent_name}/` 目录
2. 实现 `exec_agent.py`（执行入口）和核心逻辑文件
3. 创建 `prompt.md`（子 Agent 的提示词）
4. 在 `config/scheduler.json` 的 `market_subagents` 中添加配置
5. 在 `dashboard/server.py` 的 `BUILTIN_SUBAGENT_NAMES` 中添加名称（允许通过 Dashboard 配置）
6. 子 Agent 通过写入 `logs/events.jsonl` 与主 Agent 通信

### 7.4 添加新的市场阶段

1. 在 `workspace/phases/` 下创建 `{phase_name}.md`
2. 在 `runtime/build_context.py` 的 `detect_market_phase()` 中添加时间判断逻辑
3. 在 `config/scheduler.json` 的 `fixed_jobs` 中添加对应任务

### 7.5 修改输出协议

1. 更新 `system/output_contract.md`
2. 更新 `runtime/agent_loop.py` 的 `OUTPUT_FORMAT_REQUIREMENTS` 字典
3. 更新 `assess_model_output_format()` 校验逻辑
4. 更新 `build_error_retry_message()` 中的字段说明

---

## 8. 安全架构

### 8.1 安全边界

```
外部网络 ──── 不可达 ────→ │ 127.0.0.1:8787 Dashboard │
                          └───────────────────────────┘
                                  │ 无认证
                                  ▼
                          ┌─────────────────┐
                          │  LLM API 调用   │ ← API Key 仅存于 .env
                          └─────────────────┘

Agent ──→ Tool Layer ──→ File Tools（限制在 workspace/ 内）
                        └─ Exec Tool（白名单命令 + 黑名单 Token）
```

### 8.2 路径防护

所有文件操作必须通过 `FileTools._validate_path()`，确保路径在 workspace 目录内。

### 8.3 命令防护

Exec 工具限制可执行命令为白名单中的 11 个命令，并阻止 17 个危险标记。

### 8.4 数据持久化保护

- `.env` 被 `.gitignore` 排除
- `workspace/state/*.json` 和 `workspace/pools/*.jsonl` 被 `.gitignore` 排除
- 报���文件、日记忆、运行时输出均被 `.gitignore` 排除
- Dashboard 在 UI 中对密钥脱敏（仅显示末 4 位）

### 8.5 写操作回滚

JSON/JSONL 文件写入前做快照，Schema 校验失败时自动回滚，防止损坏工作区数据。

---

## 9. 调试与监控

### 9.1 运行轨迹追踪

每次运行在 `workspace/logs/agent_runs/{run_id}/` 下生成：
- `step_*_input.json` — 发送给 LLM 的 messages
- `step_*_output.json` — LLM 返回输出 + 解析结果
- `step_*_tool_result.json` — 工具执行结果
- `run_summary.json` — 汇总信息

### 9.2 Dashboard 监控

在浏览器中查看实时工作流状态，包括当前 step、thinking 内容、工具调用等。

### 9.3 CLI 直接运行

```bash
# 人工任务
make manual TASK="分析当前持仓"

# 调度模式
make scheduler

# 单次调度
make run

# 子 Agent 测试
python -m subagent.holding_follow.exec_agent --dry-run
```

---

## 10. 常见修改场景

### 10.1 修改投资风格

编辑 `config/investment_style.json` 或通过 Dashboard "投资风格"页面调整。

### 10.2 修改调度策略

编辑 `config/scheduler.json`（固定任务时间、交易时段间隔、子 Agent 配置），修改后自动重启。

### 10.3 添加新模型

在 `.env` 中设置 `LLM_URL` 和 `LLM_MODEL`，支持所有 OpenAI 兼容接口。

### 10.4 调整初始资金

修改 `initialization.sh` 中的 `account_state.json` 生成部分，或 `runtime/build_context.py:12` 的 `TURE_ASSET`（注意变量名拼写）。

### 10.5 修改最大循环步数

- 命令行: `--max-steps 50`
- Dashboard: POST /api/manual-run 的 `max_steps` 参数
- 代码默认: `runtime/agent_loop.py:run_agent_loop()` 参数默认值
