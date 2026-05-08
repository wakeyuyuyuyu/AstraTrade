---
name: tradingagents-analysis
version: 0.6.1
description: 本地 TradingAgents-AShare A股多智能体投研分析工具。通过本地部署的 TradingAgents API，对个股进行技术面、基本面、情绪、新闻、资金与风控分析，输出结构化交易建议。
homepage: http://localhost:8000
repository: https://github.com/KylinMountain/TradingAgents-AShare
tags:
  - A股
  - 股票分析
  - 投研
  - 多智能体
  - 技术分析
  - 基本面分析
  - 资金流向
  - 风险评估
  - 持仓分析
  - 候选股确认
  - openclaw
metadata:
  openclaw:
    requires:
      env:
        - TRADINGAGENTS_TOKEN
        - TRADINGAGENTS_API_URL
      bins:
        - curl
        - python3
        - bash
    primaryEnv: TRADINGAGENTS_TOKEN
    emoji: "📈"
    homepage: http://localhost:8000
---

# TradingAgents 本地 A股投研分析

本技能用于调用本地部署的 TradingAgents-AShare 服务，对 A 股个股进行深度分析。
环境变量统一存放在项目根目录 `.env` 中，由 `scripts/analyze.sh` 自动加载。

---

## 使用方式

```bash
bash scripts/analyze.sh <symbol[,symbol2,...]> [trade_date] [horizons]
```

示例：

```bash
bash scripts/analyze.sh 贵州茅台
bash scripts/analyze.sh 600519.SH 2026-04-30 short
bash scripts/analyze.sh 600519.SH 2026-04-30 short,medium
bash scripts/analyze.sh 贵州茅台,比亚迪,宁德时代
```

---

## 环境变量

```bash
TRADINGAGENTS_TOKEN=ta-sk-xxxx
TRADINGAGENTS_API_URL=http://localhost:8000
```

---

## 使用场景

- 候选股深度确认
- 持仓风险分析
- 策略生成前验证
- 盘后复盘

---

## Agent 调用示例

```json
{
  "type": "tool_call",
  "tool": "exec",
  "args": {
    "command": "bash scripts/analyze.sh 贵州茅台",
    "cwd": "workspace/skills/tradingagents-analysis"
  },
  "reason": "调用 TradingAgents 对候选股进行深度分析"
}
```

---
