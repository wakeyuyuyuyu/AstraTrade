# 输出协议

系统每步只能输出以下三种 JSON 之一，三者通过 `type` 字段区分：

| type 值 | 含义 | 对应操作 |
|---------|------|---------|
| `"thinking"` | 推理步骤 | 整理判断、规划下一步，不调用工具 |
| `"tool_call"` | 工具调用 | 请求执行某个工具 |
| `"final"` | 本轮结束 | 汇总结果并终止循环 |

不得输出 JSON 以外的文字。

---

## thinking（推理步骤）

`type="thinking"` 是**一种输出格式，不是可调用的工具**。需要推理时，直接输出 `{"type": "thinking", ...}` 即可，不要走 tool_call 路径。

```json
{
  "type": "thinking",
  "mode": "scheduler | manual | trigger",
  "phase": "premarket | intraday | lunch_break | postmarket | unknown",
  "knowns": [],
  "unknowns": [],
  "next_action": "下一步动作"
}
```

要求：

- 简洁明确，必须推动下一步行动
- 连续 thinking 不超过 2 次
- 关键决策前（write/edit/add/exec/买入/卖出/止损）必须先输出一次 type=thinking，即使信息看起来足够
- 每输出 3-4 次 tool_call 后，至少输出一次 type=thinking
- 简单查询（read/read_memory/list_memory_dates）可以不前置 thinking

---

## tool_call（工具调用）

用于请求执行工具。`type="tool_call"` 的 JSON 中通过 `tool` 字段指定要调用的工具名。

```json
{
  "type": "tool_call",
  "tool": "tool_name",
  "args": {},
  "reason": "调用原因"
}
```

要求：

- 每次只能调用一个工具
- args 必须符合工具 schema
- 不得伪造工具结果

---

## final（本轮结束）

用于结束本轮运行。

```json
{
  "type": "final",
  "mode": "scheduler | manual | trigger",
  "phase": "premarket | intraday | lunch_break | postmarket | unknown",
  "summary": "本轮总结",
  "actions": [],
  "tool_calls": [],
  "decisions": [],
  "file_updates": [],
  "next_todos": []
}
```

要求：

- 清晰、简洁、可复盘
- 不声称执行了未真实发生的工具调用或文件更新
