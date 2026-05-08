# 文件读写协议

workspace 是你的唯一外部记忆。

## 常用文件

### state
- `state/account_state.json`
- `state/market_state.json`

### pools
- `pools/holdings.jsonl`
- `pools/strategies.jsonl`
- `pools/candidates.jsonl`

### logs
- `logs/trades.jsonl`
- `logs/decisions.jsonl`
- `logs/events.jsonl`

### phases
- `phases/premarket.md`
- `phases/intraday.md`
- `phases/postmarket.md`

## 写入位置

- 生成或更新策略 → `pools/strategies.jsonl`
- 执行交易 → `logs/trades.jsonl`
- 关键决策 → `logs/decisions.jsonl`
- 重要事件 → `logs/events.jsonl`
- 更新持仓 → `pools/holdings.jsonl`
- 更新账户状态 → `state/account_state.json`

## 写入规则

- 修改文件前必须先读取相关文件
- JSONL 文件默认使用 `add` 追加写
- 当需要删除JSONL 文件中的某行时，默认使用 `edit` 手动修改
- 不得用 `write` 覆盖 JSONL 文件
- 不删除历史记录
- `state` 文件允许覆盖，但必须保留关键字段
- memory 目录不得用 `write` 或 `edit` 手动修改
- memory 内容必须通过 `write_memory` 写入

## 格式要求

所有结构化文件写入前，必须使用 `astra-trade-schema` skill 确认目标文件格式。
同一轮中再次写入同类文件时，如果已读取对应 reference，可复用该 schema 信息。

执行写入前必须按顺序完成：

1. 读取 `skills/astra-trade-schema/SKILL.md`
2. 根据 SKILL.md 的指引，读取目标文件对应的 reference
3. 再执行 `write`、`edit`、`add` 或 `write_memory`

不得跳过 schema skill 直接写入结构化文件。
