---
name: stock-ranker
version: 0.1.0
description: A股筛选股票工具。基于市场、计划、候选池、热点、资金与事件信息，筛选少量高质量候选股票。
tags:
  - A股
  - 盘前
  - 选股
  - 候选池
  - 股票推荐
  - 量化打分
  - openclaw
---

## 输出规范

输出格式请严格参考：

skills/astra-trade-schema/references/pools.md

---

## 输入来源

Agent 可参考以下信息：

- state/market_state.json
- state/account_state.json
- pools/candidates.jsonl
- pools/strategies.jsonl
- memory/<latest>/plan.md

必要时使用：

- mx-data：行情、指数、板块、资金、成交数据
- mx-search：新闻、公告、政策、研报、事件信息

---

## 操作流程

### 1. 判断市场环境

结合数据与事件判断：

- 指数强弱
- 板块热点
- 市场情绪
- 资金方向

---

### 2. 构建初筛池

候选来源：

1. 上一交易日 plan
2. 当前候选池
3. 热点板块
4. 事件驱动标的

合并去重。

---

### 3. 打分

根据以下因素综合打分：

- 趋势结构
- 资金变化
- 新闻 / 公告 / 政策
- 板块强度
- 风险水平

低质量标的不输出。

---

### 4. 筛选

- 最多输出 5 条
- 优先 3 条
- 无触发条件或风险不可判断 → 不输出

---

## 字段规则

详细字段定义请参考：

references/output-format.md

---

## 输出要求

- 只输出 JSON 数组
- 不输出解释性文字
- 每条记录必须完整
- evidence 不能为空
- 数据不足时返回：[]

---

## Agent 使用方式

对每条结果调用：

add(
  path="pools/candidates.jsonl",
  content=<单条JSON字符串>
)

---

## 限制

- 不执行交易
- 不生成策略
- 不调用重型分析做全市场扫描
- 不输出超过 5 条
- 不基于猜测生成候选
