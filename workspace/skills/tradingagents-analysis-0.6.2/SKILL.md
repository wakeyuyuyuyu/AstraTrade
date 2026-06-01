---
name: tradingagents-analysis
version: 0.6.2
description: AstraTrade 的外部重型个股深度分析技能。用于对单只或少量沪深 A 股进行多智能体投研分析，并把结果作为候选池、策略、持仓风控或复盘决策的证据来源。适用于用户明确要求个股深度分析、持仓复核、候选验证、买卖条件评估或风险复盘的场景。
tags:
  - A股
  - 个股分析
  - 深度投研
  - 持仓复核
  - 候选验证
  - 风险评估
required_env_vars:
  - TRADINGAGENTS_TOKEN
optional_env_vars:
  - TRADINGAGENTS_API_URL
  - POLL_INTERVAL
  - POLL_TIMEOUT
credentials:
  - type: api_token
    name: TRADINGAGENTS_TOKEN
    description: TradingAgents API 访问令牌
---

# TradingAgents 个股深度分析

本 Skill 用于在 AstraTrade 中调用外部 TradingAgents 分析服务，对指定 A 股做深度研判。它是一个重型证据工具，不是交易执行器；分析结果必须与工作空间状态、风控规则和其他数据源共同使用。

## 适用场景

适合使用：

- 用户明确要求分析某只 A 股是否值得关注、买入、卖出、继续持有或加入候选池。
- 主 Agent 需要对候选股、持仓股或已有策略做二次验证。
- 盘后复盘、风险复核、重要事件后的个股再评估。
- 需要获得技术面、基本面、情绪、资金流向、宏观和风险维度的综合结论。

不适合使用：

- 全市场扫描或大批量选股；这类任务优先使用 `stock-ranker`。
- 分钟级盘中盯盘、超短线即时交易或实时成交决策。
- 非 A 股市场、加密货币、美股等标的。
- 绕过 AstraTrade 风控规则直接生成或执行交易。

## 输入规则

从用户任务或工作空间上下文中只提取必要参数：

- `symbol`：股票名称或代码，例如 `贵州茅台`、`600519.SH`、`宁德时代`。
- `trade_date`：分析日期。用户未指定时使用当前日期或当前交易日。
- `horizons`：分析周期。未指定时使用 `short`；波段或更完整复核可使用 `medium`；需要多周期交叉验证时使用逗号分隔，例如 `short,medium`。

不要把用户完整对话、账户隐私、真实持仓明细或无关本地文件内容传给外部服务。脚本只需要股票标的、日期和周期参数。

## 调用方式

AstraTrade Agent 使用 `exec` 工具调用脚本。`exec.cwd` 默认以 `workspace/` 为基准，因此脚本路径应写成：

```json
{
  "type": "tool_call",
  "tool": "exec",
  "args": {
    "command": "bash skills/tradingagents-analysis-0.6.2/scripts/analyze.sh 贵州茅台 2026-05-26 short",
    "cwd": "."
  },
  "reason": "调用 TradingAgents 获取贵州茅台的深度分析"
}
```

常用命令：

```bash
bash skills/tradingagents-analysis-0.6.2/scripts/analyze.sh 贵州茅台
bash skills/tradingagents-analysis-0.6.2/scripts/analyze.sh 600519.SH 2026-05-26 short
bash skills/tradingagents-analysis-0.6.2/scripts/analyze.sh 600519.SH 2026-05-26 short,medium
bash skills/tradingagents-analysis-0.6.2/scripts/analyze.sh 贵州茅台,比亚迪,宁德时代 2026-05-26 short
```

脚本会自动完成提交任务、轮询状态和获取结果。不要手写 `curl` 轮询循环，也不要把 API 调用逻辑复制到 prompt 中。

## 执行约束

- 深度分析通常耗时 10 到 20 分钟，只对单只或少量标的使用。
- 批量分析只用于少量明确标的，通常不超过 3 只。
- 轮询间隔由 `POLL_INTERVAL` 控制，默认 15 秒；最大等待时间由 `POLL_TIMEOUT` 控制，默认 1200 秒。
- 缺少 `TRADINGAGENTS_TOKEN` 时，停止调用并说明需要配置凭证，不得编造结果。
- 网络错误、任务失败或超时时，保留错误信息和 `job_id`，并根据任务需要改用 `mx-data`、`mx-search` 或稍后复查。

## 结果处理

脚本返回 JSON 后，先提取对决策有用的字段，再结合 AstraTrade 工作空间状态判断下一步：

- 结论：`decision`、`direction`、`confidence`。
- 价格与条件：目标价、止损价、关键触发条件。
- 风险：`risk_items`、负面因素、失效条件。
- 依据：技术面、基本面、资金、情绪、事件或宏观相关证据。
- 备注：`final_trade_decision` 或等价的最终分析文本。

面向用户或最终结果时，用中文给出简洁摘要，重点说明：

- 分析结论及置信度。
- 支撑结论的 3 到 5 条关键依据。
- 主要风险和需要继续验证的数据。
- 对候选、持仓、策略或复盘的建议动作。

不要原样倾倒大段 JSON；除非用户明确要求查看原始返回。

## 与工作空间的关系

TradingAgents 的结果只能作为外部证据，不能单独触发交易。涉及工作空间写入时必须遵守 AstraTrade 文件协议：

- 写入 `pools/candidates.jsonl`、`pools/strategies.jsonl`、`pools/holdings.jsonl`、`logs/events.jsonl` 或 `logs/trades.jsonl` 前，必须先使用 `astra-trade-schema` 读取对应 schema reference。
- JSONL 文件只能追加或精确编辑，不得直接覆盖。
- 买入、卖出、调仓、策略变更必须先读取账户、持仓、策略和风控状态。
- 若分析结果改变了重要判断，可以把它作为 evidence 写入候选、策略或事件记录，来源标记为 `tradingagents-analysis`。
- 若只是回答用户研究问题且不需要更新状态，不要强行写入工作空间。

## 安全说明

- 外部发送范围仅限 `symbol`、`trade_date`、`horizons`。
- `TRADINGAGENTS_TOKEN` 只通过环境变量读取，不得写入日志、报告或用户可见内容。
- 本 Skill 输出不构成投资建议，也不能替代用户对行情、账户、风险和交易规则的独立核验。
