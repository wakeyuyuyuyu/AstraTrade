# 输出协议

系统循环过程中只能输出三种 JSON：

1. `thinking`
2. `tool_call`
3. `final`

不得输出 JSON 以外的文字。

---

## thinking

用于整理当前判断和下一步行动。

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

- 简洁明确
- 必须推动下一步行动
- 连续 thinking 不超过 2 次
- 信息不足时优先 tool_call

---

## tool_call

用于请求执行工具。

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

## final

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

- 清晰
- 简洁
- 可复盘
- 不声称执行了未真实发生的工具调用或文件更新
