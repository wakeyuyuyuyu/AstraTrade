---
name: astra-trade-schema
description: AstraTrade workspace 的 schema 指引，用于决定在写入 state、pools、logs、reports 或 agent run 文件前应读取哪个 schema reference。当 Agent 需要创建、更新、追加、校验或检查 AstraTrade workspace 中的结构化文件时使用，例如 state/*.json、pools/*.jsonl、logs/*.jsonl、reports/*.json 或 logs/agent_runs/*。
---

# AstraTrade Schema

当需要写入或校验 AstraTrade workspace 数据时，使用此 skill。

目标是减少 schema 占用的上下文：不要加载所有 schema 文件，只读取目标文件所需的 reference。

## 工作流程

1. 识别目标文件路径。
2. 读取匹配的 reference 文件。
3. 根据对应 reference 写入或校验 JSON / JSONL。
4. 如果不确定通用字段，读取 `references/common.md`。

## Reference 选择规则

- `state/*.json` → 读取 `references/state.md`
- `pools/*.jsonl` → 读取 `references/pools.md`
- `logs/*.jsonl` → 读取 `references/logs.md`
- `reports/*.json` → 读取 `references/reports.md`
- `logs/agent_runs/*` → 读取 `references/reports.md`
- 通用枚举、时间格式、ID 规则、evidence 格式 → 读取 `references/common.md`

## 强制规则

- JSONL 文件必须追加写入，不得覆盖。
- State JSON 文件可以覆盖，但必须保留关键字段。
- 传给文件工具的 `content` 必须是合法 JSON。
- 不得编造工具结果、行情、交易或市场数据。
- 子 Agent 触发事件必须写入 events。
