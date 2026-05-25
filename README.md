<div align="center">
  <img src="assets/astra-trade-logo.png" alt="AstraTrade Logo" width="420">
  <br>
  <p><strong>面向 A 股研究、模拟交易与自动化决策的本地 Agent 控制台</strong></p>
  <p>
    <a href="https://github.com/BryanGao-1216/AstraTrade">GitHub Repository</a>
    ·
    <a href="#快速开始">快速开始</a>
    ·
    <a href="#控制台能力">控制台能力</a>
    ·
    <a href="#系统流程图">系统流程图</a>
    ·
    <a href="#运行模式">运行模式</a>
    ·
    <a href="#数据文件">数据文件</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/Dashboard-Local%20Web-20d0a2" alt="Local Dashboard">
    <img src="https://img.shields.io/badge/LLM-OpenAI%20Compatible-7c3aed" alt="OpenAI Compatible LLM">
    <img src="https://img.shields.io/badge/Market-A%20Share-f59e0b" alt="A Share Market">
    <img src="https://img.shields.io/badge/Workspace-Local%20Memory-64a8ff" alt="Local Workspace">
    <img src="https://img.shields.io/badge/License-Private-lightgrey" alt="Private License">
  </p>
</div>

---

## 核心亮点

| 重点 | 说明 |
| --- | --- |
| 三种唤醒模式 + Alarm | 主 Agent 支持 `scheduler` 定时巡检、`manual` 人工指令、`trigger` 事件触发；Alarm 可把一次性或周期性任务转成到点自动执行的人工任务 |
| 三类交易工作池 | `持仓池` 跟踪当前仓位和盈亏，`策略池` 保存买卖计划与风控条件，`候选池` 沉淀观察标的和触发条件 |
| 主 Agent / 子 Agent 协作 | 主 Agent 负责综合判断、文件更新和最终决策；持仓/候选子 Agent 负责盘中盯盘，满足条件时唤醒主 Agent |
| 模型分层配置 | 主 Agent 使用 `LLM_*` 配置；子 Agent 使用 `SUB_LLM_*` 配置 |

## 系统流程图

<p align="center">
  <img src="assets/astra-trade-system-architecture.png" alt="AstraTrade System Architecture">
</p>

## 项目简介

`AstraTrade` 是一个本地优先的 A 股研究与模拟交易 Agent 系统，用于自动化市场盯盘、策略制定、模拟交易记录和复盘分析。系统以 `workspace/` 作为本地工作空间，围绕账户状态、市场状态、持仓池、策略池、候选池组织日常工作。

支持自定义配置投资风格，子 Agent 在开盘期间自动执行盯盘；主 Agent 支持 `manual`、`scheduler`、`trigger` 三种唤醒模式，并可通过 Alarm 将自然语言提醒转化为到点执行的任务。

> 免责声明：本项目用于研究、模拟交易、策略验证和自动化复盘，不构成投资建议。任何真实交易动作都应由用户自行核验行情、账户、持仓、风控和工具返回结果后再决定。

## 一眼看懂

| 能力 | 说明 |
| --- | --- |
| 多模式唤醒 | `manual`、`scheduler`、`trigger` 三种主 Agent 调用方式，并支持 Alarm 定时触发人工任务 |
| 池子体系 | 持仓池、策略池、候选池分别承载当前仓位、执行计划和观察标的 |
| Agent 协作 | 主 Agent 负责最终判断，持仓/候选子 Agent 负责盘中监控；主/子 Agent 可分别配置模型 |
| 本地控制台 | 账户状态、市场状态、池子看板、调度配置、人工指令、运行轨迹集中在一个 dashboard |
| 自动巡检 | 支持盘前唤醒、盘中巡检、盘后复盘，以及持仓/候选池子 Agent 盯盘 |
| 长期记忆 | 所有状态、日志、报告、策略与 skills 保存在 `workspace/`，便于回溯和迁移 |
| 风格约束 | 通过 `config/investment_style.json` 生成 `workspace/STYLE.md`，约束交易周期、风险偏好和仓位风格 |
| 受控写入 | `read/write/edit/add/exec` 统一经过工具层；结构化文件写入后会按 schema 校验，失败会返回明确错误 |
| 结构化复盘 | 每轮 Agent 调用会落盘 prompt、逐步输入输出、工具结果、run summary 和完整运行轨迹 |
| 金融 Skills | 集成 `mx-data`、`mx-search`、`mx-moni` 等本地 skill，用于行情、资讯和模拟交易 |

## 快速开始

dashboard 是项目的默认入口。新用户建议先启动本地控制台，再通过页面完成 API 配置、投资风格配置、scheduler 配置、人工指令提交和运行轨迹复盘。

### 1. 克隆项目

```bash
git clone https://github.com/BryanGao-1216/AstraTrade.git
cd AstraTrade
```

### 2. 一键初始化

```bash
make setup
```

`make setup` 会完成：

- 创建 `.venv`
- 安装 `requirements.txt`
- 从 `.env.example` 复制生成本地 `.env`
- 初始化缺失的 `workspace` 状态文件
- 生成 `workspace/STYLE.md`

### 3. 配置 API

编辑 `.env`，填入自己的 API Key 和模型配置：

```bash
LLM_API_KEY=your_llm_api_key
LLM_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your_model_name

SUB_LLM_API_KEY=your_sub_agent_llm_api_key
SUB_LLM_URL=https://your-openai-compatible-endpoint/v1
SUB_LLM_MODEL=your_sub_agent_model_name

MX_APIKEY=your_mx_api_key
MX_API_URL=https://mkapi2.dfcfs.com/finskillshub
```

`SUB_LLM_*` 用于持仓/候选子 Agent；如果不配置，会逐项回退到主 Agent 的 `LLM_*` 配置。

### 4. 启动 dashboard

```bash
make dashboard
```

默认访问地址：

```text
http://127.0.0.1:8787/
```

指定端口：

```bash
make dashboard PORT=9000
```

也可以直接启动后端：

```bash
python dashboard/server.py 8787
```

## 控制台能力

| 页面 | 能做什么 |
| --- | --- |
| 主控制台 | 查看账户状态、市场状态、持仓池、策略池、候选池和系统控制 |
| 调用轨迹 | 打开某次主 Agent 调用，复盘模型输出、工具调用和最终结果 |
| 投资风格配置 | 调整投资周期、风险偏好、选股偏好、交易频率、仓位风格和止盈止损风格 |
| API 配置 | 管理 LLM 与金融数据 API 的本地环境变量 |
| 调度配置 | 配置盘前唤醒、盘中巡检、盘后复盘和已有子 Agent 命令 |

主控制台中可以直接完成：

- 查看账户资产、现金、持仓市值、风险限制和风控状态。
- 查看市场观点、风险等级、热点主题、关注板块和关键事件。
- 输入人工指令并触发主 Agent。
- 启动或停止 scheduler。
- 初始化 workspace。
- 查看最近执行过的 scheduler 调用和时间。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `make setup` | 创建虚拟环境、安装依赖、生成 `.env` 和默认 workspace |
| `make dashboard` | 启动本地 dashboard |
| `make init` | 初始化 workspace，清空运行数据并重置账户/市场状态 |
| `make run` | 执行一次主 Agent scheduler 模式 |
| `make scheduler` | 启动常驻 scheduler |
| `make manual TASK="..."` | 执行一条人工自然语言指令 |
| `make style` | 根据投资风格配置重新生成 `workspace/STYLE.md` |
| `make check` | 编译检查主要 Python 文件 |
| `make clean` | 清理 Python 缓存文件 |

示例：

```bash
make manual TASK="检查当前持仓和候选池，给出下一步观察重点"
```

## 模块说明

| 模块 | 作用 |
| --- | --- |
| `dashboard/` | 本地控制台，用于查看状态、提交人工指令、配置风格/API/scheduler、控制 scheduler 和复盘轨迹 |
| `runtime/launcher.py` | 主 Agent 单次运行入口，负责进入 scheduler、manual 或 trigger 模式 |
| `runtime/agent_loop.py` | LLM 循环与工具调用执行器，记录每一步输入、输出、工具结果和完整轨迹 |
| `runtime/agent.py` | 常驻调度器，根据 `config/scheduler.json` 执行主 Agent 唤醒、Alarm 和盘中子 Agent 巡检 |
| `subagent/` | 持仓池和候选池盯盘逻辑 |
| `workspace/` | 本地长期记忆，保存状态、池子、日志、报告和 skills |
| `system/` | 核心提示词、模式规则、工具协议和输出协议 |
| `tools/` | 受控工具层，负责 workspace 文件读写、命令执行、skills 摘要读取和结构化文件校验 |

## 手动安装

如果不使用 `make`，可以手动执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m runtime.investment_style
bash dashboard/start.sh 8787
```

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 是 | OpenAI 兼容接口密钥 |
| `LLM_URL` | 是 | OpenAI 兼容接口地址，通常以 `/v1` 结尾 |
| `LLM_MODEL` | 是 | 主 Agent 模型名称 |
| `SUB_LLM_API_KEY` | 否 | 子 Agent OpenAI 兼容接口密钥；不填则回退 `LLM_API_KEY` |
| `SUB_LLM_URL` | 否 | 子 Agent OpenAI 兼容接口地址；不填则回退 `LLM_URL` |
| `SUB_LLM_MODEL` | 否 | 子 Agent 模型名称；不填则回退 `LLM_MODEL` |
| `MX_APIKEY` | 否 | 东方财富妙想 Skills API Key，用于金融数据、资讯和模拟组合 |
| `MX_API_URL` | 否 | 妙想 API 地址 |
| `TRADINGAGENTS_TOKEN` | 否 | TradingAgents 服务 Token |
| `TRADINGAGENTS_API_URL` | 否 | TradingAgents 服务地址 |
| `STOCK_AGENT_PYTHON` | 否 | 指定 dashboard 启动 Agent 子进程时使用的 Python |

## 运行模式

### Scheduler 模式

执行一次 scheduler 巡检：

```bash
python -m runtime.launcher --mode scheduler
```

启动常驻调度器：

```bash
python -m runtime.agent
```

调度规则位于 `config/scheduler.json`，默认包含：

- 工作日运行。
- 盘前唤醒、盘中唤醒、盘后唤醒：固定时间直接唤醒主 Agent。
- 盘中巡检：交易时段每 10 分钟先运行持仓/候选池子 Agent，再由子 Agent 按需触发主 Agent。
- 子 Agent：默认包含盘中巡检的 `holding_follow` / `candidate_follow`，以及按固定时间触发的 `trading_diary`。
- 日志写入 `workspace/logs/scheduler/`。

也可以在 dashboard 的「调度配置」页面修改这些规则。当前页面支持修改固定唤醒任务、盘中巡检时段、已有子 Agent 的启用状态、触发时间和命令；不支持用户直接新增子 Agent。

### Manual 模式

只要传入 `--task`，系统会进入人工任务模式：

```bash
python -m runtime.launcher --task "分析 300059 是否值得加入候选池"
```

### Trigger 模式

用于外部事件触发：

```bash
python -m runtime.launcher \
  --mode trigger \
  --trigger-reason manual_trigger \
  --trigger-event '{"source":"manual","symbol":"300059","trigger_type":"manual","reason":"人工检查"}'
```

## 子 Agent

子 Agent 用于盘中巡检。scheduler 会在交易时段先调用已有子 Agent，同步持仓或候选池状态，并在满足条件时按需唤醒主 Agent。

当前 dashboard 不支持用户新增子 Agent；页面只能配置已有子 Agent 的启用状态和命令。若需要新增一种子 Agent，需要在代码中实现对应模块，并同步更新调度配置与执行逻辑。

### 持仓盯盘

```bash
python -m subagent.holding_follow.exec_agent
```

常用参数：

```bash
python -m subagent.holding_follow.exec_agent --dry-run
python -m subagent.holding_follow.exec_agent --no-update
```

### 候选池盯盘

```bash
python -m subagent.candidate_follow.exec_agent
```

常用参数：

```bash
python -m subagent.candidate_follow.exec_agent --dry-run
python -m subagent.candidate_follow.exec_agent --no-update
```

## 目录结构

```text
AstraTrade/
├── config/
│   ├── investment_style.json        # 投资风格配置
│   └── scheduler.json               # 调度配置
├── dashboard/
│   ├── server.py                    # dashboard 后端
│   ├── start.sh                     # dashboard 启动脚本
│   └── static/                      # dashboard 前端
├── runtime/
│   ├── agent_loop.py                # LLM 循环和工具调用执行器
│   ├── build_context.py             # 动态上下文构建
│   ├── investment_style.py          # 投资风格生成器
│   ├── launcher.py                  # 主 Agent 单次运行入口
│   ├── render_prompt.py             # 系统 prompt 渲染
│   └── agent.py                     # 常驻调度器与 Alarm runner
├── services/
│   └── llm_service.py               # OpenAI 兼容模型调用
├── subagent/
│   ├── candidate_follow/            # 候选池盯盘子 Agent
│   └── holding_follow/              # 持仓盯盘子 Agent
├── system/
│   ├── core_prompt.md               # 核心系统提示
│   ├── file_protocol.md             # 文件读写协议
│   ├── output_contract.md           # 输出协议
│   ├── rules.md                     # 行为规则
│   ├── tools.md                     # 工具定义
│   └── modes/                       # scheduler/manual/trigger 模式规则
├── tools/
│   ├── exec.py                      # 受限命令执行
│   ├── file_tools.py                # workspace 文件工具与 schema 校验
│   └── list_skills.py               # skills 摘要读取
├── workspace/
│   ├── MARKET.md                    # A 股市场背景
│   ├── STYLE.md                     # 生成后的投资风格约束
│   ├── phases/                      # 不同交易阶段说明
│   ├── skills/                      # 本地 skills 与数据 schema
│   ├── state/                       # 账户和市场状态
│   ├── pools/                       # 持仓池、策略池、候选池
│   ├── logs/                        # 运行日志
│   └── reports/                     # prompt 和结果输出
├── .env.example                     # 环境变量模板
├── Makefile                         # 常用命令入口
├── initialization.sh                 # workspace 初始化脚本
└── requirements.txt                  # Python 依赖
```

本地运行产生的 `.env`、dashboard runtime、workspace 日志/报告/记忆、池子与状态数据，以及个人实验用的 `test/` 目录默认不提交到 GitHub。

## 数据文件

核心结构化文件定义在 `workspace/skills/astra-trade-schema/`。Agent 在写入 `state/`、`pools/`、`logs/`、`reports/` 等结构化数据前应参考该 skill；文件工具会在写入后做格式校验，发现缺字段、JSON/JSONL 解析失败或目标类型不匹配时返回错误，提示模型读取对应 schema 后重试。

| 文件 | 说明 |
| --- | --- |
| `workspace/state/account_state.json` | 账户资金、资产、仓位和风控限制 |
| `workspace/state/market_state.json` | 市场观点、风险等级、热点、关注方向 |
| `workspace/pools/holdings.jsonl` | 当前持仓 |
| `workspace/pools/strategies.jsonl` | 策略池 |
| `workspace/pools/candidates.jsonl` | 候选池 |
| `workspace/logs/trades.jsonl` | 交易记录 |
| `workspace/logs/events.jsonl` | 外部事件、子 Agent 触发事件和系统事件 |
| `workspace/logs/scheduler/` | scheduler 运行日志 |
| `workspace/logs/agent_runs/{run_id}/` | 单次 Agent 调用的逐步轨迹 |
| `workspace/logs/agent_runs/{run_id}/run_summary.json` | 单次调用摘要、耗时、工具调用历史和最终结果 |
| `workspace/logs/agent_runs/{run_id}/agent_trace.json` | 单次调用的完整消息、模型输出、工具结果和耗时轨迹 |
| `workspace/reports/{run_id}_prompt.md` | 本轮发送给模型的完整 prompt |
| `workspace/reports/{run_id}_result.json` | 本轮最终结果 |
| `workspace/skills/astra-trade-schema/` | workspace 结构化数据 schema 与写入参考 |

## 输出协议

主 Agent 最终输出遵循 `system/output_contract.md`，核心结构类似：

```json
{
  "type": "final",
  "mode": "scheduler | manual | trigger",
  "phase": "premarket | intraday | lunch_break | postmarket | non_trading_day | unknown",
  "summary": "本轮总结",
  "actions": [],
  "tool_calls": [],
  "decisions": [],
  "file_updates": [],
  "next_todos": []
}
```

循环中间输出只能是 `thinking`、`tool_call` 或 `final` 三种 JSON。若模型输出无法解析或缺少关键字段，Agent Loop 会把协议错误反馈给模型并要求重试。

## License

本项目目前为私人项目，仅用于个人研究与开发。

保留所有权利。未经许可，禁止复制、分发、修改或用于商业用途。
