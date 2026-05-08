# Pools Schemas

Files under `workspace/pools/` are JSONL. Append records; do not overwrite the whole file.

## holdings.jsonl

```json
{
  "holding_id": "string",
  "symbol": "string",
  "name": "string",
  "count": 0,
  "availCount": 0,
  "cost_price": 0,
  "current_price": 0,
  "market_value": 0,
  "unrealized_pnl": 0,
  "unrealized_pnl_pct": 0,
  "strategy_id": "string",
  "status": "holding | reducing | closed | suspended",
  "opened_at": "YYYY-MM-DD HH:MM:SS",
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "notes": "string"
}
```

## strategies.jsonl

```json
{
  "strategy_id": "string",
  "symbol": "string",
  "name": "string",
  "source": "scheduler | manual | trigger | premarket | intraday | postmarket | news | ranker",
  "strategy_type": "string",
  "status": "active | pending | watching | trigger_ready | triggered | completed | expired | invalidated",
  "priority": "low | medium | high",
  "entry_conditions": [],
  "exit_conditions": [],
  "stop_loss": {
    "type": "price | percent",
    "value": 0,
    "reason": "string"
  },
  "position_plan": {
    "max_position_ratio": 0,
    "suggested_cash_ratio": 0
  },
  "valid_until": "YYYY-MM-DD HH:MM:SS",
  "created_at": "YYYY-MM-DD HH:MM:SS",
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "evidence": [],
  "notes": "string"
}
```

## candidates.jsonl

```json
{
  "candidate_id": "string",
  "symbol": "string",
  "name": "string",
  "reason": "string",
  "source": "scheduler | manual | trigger | premarket | intraday | postmarket | news | ranker",
  "tags": [],
  "score": 0,
  "status": "watching | ready | promoted | rejected | expired",
  "current_price": 0,
  "trigger": {
    "type": "price_above | price_below | pullback | breakout | manual | event",
    "price": 0,
    "condition": "string"
  },
  "buy_plan": {
    "planned_quantity": 0,
    "planned_cash": 0,
    "max_position_ratio": 0
  },
  "risk": {
    "stop_loss_price": 0,
    "take_profit_price": 0,
    "invalid_price": 0
  },
  "valid_until": "YYYY-MM-DD HH:MM:SS",
  "added_at": "YYYY-MM-DD HH:MM:SS",
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "evidence": [],
  "next_action": "string",
  "notes": "string"
}
```
