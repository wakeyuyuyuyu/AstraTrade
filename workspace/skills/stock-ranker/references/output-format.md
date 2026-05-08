# Output Format

必须输出 JSON 数组，每个元素为一条 candidates.jsonl 记录。

```json
[
  {
    "candidate_id": "cand_YYYYMMDD_SYMBOL",
    "symbol": "string",
    "name": "string",
    "reason": "string",
    "source": "premarket",
    "tags": [],
    "score": 0,
    "status": "watching",
    "current_price": 0,
    "trigger": {
      "type": "price_above",
      "price": 0,
      "condition": "string"
    },
    "buy_plan": {
      "planned_quantity": 0,
      "planned_cash": 0,
      "max_position_ratio": 0.1
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
    "next_action": "watch",
    "notes": ""
  }
]