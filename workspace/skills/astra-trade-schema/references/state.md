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
  "market_sentiment": {
    "score": 0,
    "label": "extreme_bearish | bearish | neutral | bullish | overheated | unknown",
    "reason": "string"
  },
  "summary": "string",
  "hot_topics": [],
  "watch_sectors": [],
  "avoid_sectors": [],
  "key_events": [],
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "evidence": []
}
```
### market_sentiment_score

市场情绪量化分数，取值范围为 0-100。

- 0-20：极度悲观，市场风险偏高，优先防守
- 21-40：偏弱，谨慎观察，减少新增交易
- 41-60：中性，结构性机会为主
- 61-80：偏积极，可适度提高观察和交易频率
- 81-100：过热，情绪高涨但需警惕回落和追高风险

### market_sentiment_reason

市场情绪量化分数的解释，简短陈述即可。
