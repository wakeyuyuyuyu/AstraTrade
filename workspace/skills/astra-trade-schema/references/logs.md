# Log Schemas

Files under `workspace/logs/` are JSONL. Append records; do not overwrite the whole file.

## agent_runs.jsonl

```json
{
  "timestamp": "YYYY-MM-DD HH:MM:SS",
  "run_id": "string",
  "mode": "scheduler | manual | trigger",
  "trigger_reason": "string",
  "user_task": "string",
  "trigger_event": {},
  "prompt_file": "string",
  "result_file": "string",
  "run_log_dir": "string",
  "success": true,
  "phase": "premarket | intraday | lunch_break | postmarket | non_trading_day | unknown",
  "summary": "string"
}
```

## events.jsonl

```json
{
  "event_id": "string",
  "timestamp": "YYYY-MM-DD HH:MM:SS",
  "source": "holding_follow | scheduler | manual | trigger | mx-search | system",
  "event_type": "subagent_trigger | price_break | stop_loss | take_profit | news | announcement | manual_task | system_error",
  "symbol": "string",
  "name": "string",
  "strategy_id": "string",
  "trigger_type": "string",
  "reason": "string",
  "trigger_event": {},
  "status": "new | handled | ignored | failed",
  "run_id": "string"
}
```

## trades.jsonl

```json
{
  "trade_id": "string",
  "timestamp": "YYYY-MM-DD HH:MM:SS",
  "mode": "scheduler | manual | trigger",
  "trigger_reason": "string",
  "symbol": "string",
  "name": "string",
  "side": "buy | sell",
  "quantity": 0,
  "price": 0,
  "amount": 0,
  "fee": 0,
  "strategy_id": "string",
  "decision_id": "string",
  "order_id": "string",
  "status": "simulated_submitted | simulated_filled | rejected | cancelled | failed",
  "reason": "string",
  "created_by": "agent | manual | subagent"
}
```
