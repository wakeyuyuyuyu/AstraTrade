# Reports Schemas

Use this reference for `reports/*.json` and `logs/agent_runs/*`.

## reports/{run_id}_result.json

```json
{
  "success": true,
  "type": "final",
  "mode": "scheduler | manual | trigger",
  "phase": "premarket | intraday | lunch_break | postmarket | non_trading_day | unknown",
  "summary": "string",
  "actions": [],
  "tool_calls": [],
  "decisions": [],
  "file_updates": [],
  "next_todos": []
}
```

Extra fields are allowed, but preserve the fields above when possible.

## logs/agent_runs/{run_id}/run_summary.json

```json
{
  "timestamp": "YYYY-MM-DD HH:MM:SS",
  "success": true,
  "mode": "scheduler | manual | trigger",
  "phase": "premarket | intraday | lunch_break | postmarket | non_trading_day | unknown",
  "summary": "string",
  "steps": 0,
  "tool_call_count": 0,
  "tool_call_history": [],
  "final_result": {}
}
```

## logs/agent_runs/{run_id}/step_*.json

Recommended shape:

```json
{
  "timestamp": "YYYY-MM-DD HH:MM:SS",
  "step": 1,
  "messages": [],
  "raw_output": "string",
  "parsed_output": {},
  "tool": "string",
  "args": {},
  "result": {}
}
```

Step files may contain only the fields relevant to that step.
