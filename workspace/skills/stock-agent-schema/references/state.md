# State Schemas

Files under `workspace/state/` are single JSON files. They may be overwritten, but key fields must be preserved.

## account_state.json

```json
{
  "mode": "initialization | paper | live",
  "cash": 0,
  "total_asset": 0,
  "market_value": 0,
  "available_cash": 0,
  "position_count": 0,
  "risk": {
    "max_position_ratio": 0,
    "max_single_stock_ratio": 0,
    "max_daily_trades": 0,
    "stop_trading": false
  },
  "updated_at": "YYYY-MM-DD HH:MM:SS"
}
```

## market_state.json

```json
{
  "date": "YYYY-MM-DD",
  "market_view": "bullish | bearish | neutral | warm | weak | unknown",
  "risk_level": "low | medium | high | unknown",
  "summary": "string",
  "hot_topics": [],
  "watch_sectors": [],
  "avoid_sectors": [],
  "key_events": [],
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "evidence": []
}
```
