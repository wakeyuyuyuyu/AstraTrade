# Common Schema Rules

## Time

Use:

```text
YYYY-MM-DD HH:MM:SS
```

Use date-only format only where explicitly expected:

```text
YYYY-MM-DD
```

## mode

```text
scheduler | manual | trigger
```

- scheduler: system scheduled run
- manual: human natural-language call
- trigger: event-triggered call

## trigger_reason

Common values:

```text
scheduled_run
scheduled_premarket
scheduled_intraday
scheduled_lunch_break
scheduled_postmarket
manual_run
trigger_run
holding_follow_trigger
```

Other readable strings are allowed when needed.

## phase

```text
premarket | intraday | lunch_break | postmarket | non_trading_day | unknown
```

Use `unknown` when the task is not market-phase dependent.

## ID format

Recommended:

```text
{type}_{symbol}_{YYYYMMDDHHMMSS}
```

Examples:

```text
decision_600519_20260507143000
trade_600519_20260507143000
event_600519_20260507143000
```

## evidence

Recommended shape:

```json
[
  {
    "type": "quote | news | strategy | tool_result | manual_input",
    "source": "string",
    "summary": "string",
    "value": {}
  }
]
```

## General principles

- Do not write unconfirmed data.
- Do not fabricate tool results.
- Do not use vague reasons for critical decisions.
- Trading, strategy, risk, and trigger records must be reviewable.
