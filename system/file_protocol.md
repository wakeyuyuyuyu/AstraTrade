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
- `logs/events.jsonl`

### phases
- `phases/premarket.md`
- `phases/intraday.md`
- `phases/postmarket.md`

## 写入位置

- 生成或更新策略 → `pools/strategies.jsonl`
- 执行交易 → `logs/trades.jsonl`
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

写入结构化文件时，必须确认目标文件格式。相关 Schema 参考已包含在本轮运行上下文中，无需额外读取 `skills/astra-trade-schema/` 文件。

如果上下文中的 Schema 信息不足以确认格式，可读取对应的 reference 文件进行补充验证。
