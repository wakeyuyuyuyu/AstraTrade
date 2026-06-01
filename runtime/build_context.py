from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_MODES = {"scheduler", "manual", "trigger"}
# TURE_ASSET = 20000
TURE_ASSET = 1000000

@dataclass
class RuntimeContext:
    now: str
    date: str
    weekday: str
    market_phase: str

    # invocation info
    mode: str
    trigger_reason: str
    user_task: str
    trigger_event: Dict[str, Any]

    # state
    account_state: Dict[str, Any]
    market_state: Dict[str, Any]

    # summaries
    holdings_summary: Dict[str, Any]
    strategies_summary: Dict[str, Any]
    candidates_summary: Dict[str, Any]

    # recent logs
    recent_trades: List[Dict[str, Any]]
    recent_events: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


WEEKDAY_MAP = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


def normalize_mode(mode: str | None) -> str:
    if not mode:
        return "scheduler"

    mode = mode.strip().lower()

    # tolerate typo from config / CLI
    if mode == "schrduler":
        mode = "scheduler"

    if mode not in VALID_MODES:
        return "scheduler"

    return mode


def read_json_file(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default or {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else (default or {})
    except Exception:
        return default or {}


def read_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    items: List[Dict[str, Any]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                items.append(obj)
        except Exception:
            continue

    return items


def tail_jsonl(path: Path, n: int = 5) -> List[Dict[str, Any]]:
    items = read_jsonl_file(path)
    return items[-n:]


def filter_related_items(items: List[Dict[str, Any]], symbol: str | None) -> List[Dict[str, Any]]:
    """Filter JSONL items by stock symbol if provided."""
    if not symbol:
        return items

    result: List[Dict[str, Any]] = []
    for item in items:
        item_symbol = item.get("symbol") or item.get("code") or item.get("stock_code")
        if item_symbol == symbol:
            result.append(item)

    return result


def detect_market_phase(now: datetime) -> str:
    """
    A股粗粒度阶段判断：
    - 09:30-11:30: 盘中
    - 11:30-13:00: 午休
    - 13:00-15:00: 盘中
    - 15:00 之后: 盘后
    - 09:30 之前: 盘前
    - 周末: 非交易日
    """
    if now.weekday() >= 5:
        return "非交易日"

    current = now.time()

    if current < time(9, 30):
        return "盘前"
    if time(9, 30) <= current < time(11, 30):
        return "盘中"
    if time(11, 30) <= current < time(13, 0):
        return "午休"
    if time(13, 0) <= current < time(15, 0):
        return "盘中"

    return "盘后"


def summarize_holdings(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {
            "count": 0,
            "symbols": [],
            "total_quantity": 0,
            "notes": "当前无持仓",
        }

    symbols: List[str] = []
    total_quantity = 0

    for item in items:
        symbol = item.get("symbol") or item.get("code") or item.get("stock_code")
        if symbol:
            symbols.append(symbol)

        quantity = item.get("quantity")
        if quantity is None:
            quantity = item.get("count")
        if quantity is None:
            quantity = item.get("shares")
        if quantity is None:
            quantity = 0

        if isinstance(quantity, (int, float)):
            total_quantity += quantity

    return {
        "count": len(items),
        "symbols": symbols,
        "total_quantity": total_quantity,
        "notes": f"当前共有 {len(items)} 条持仓记录",
    }


def summarize_strategies(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {
            "count": 0,
            "active_count": 0,
            "symbols": [],
            "notes": "当前无策略",
        }

    active_status = {"active", "pending", "watching", "trigger_ready", "待执行", "执行中"}
    active_count = 0
    symbols: List[str] = []

    for item in items:
        status = item.get("status", "")
        if status in active_status:
            active_count += 1

        symbol = item.get("symbol") or item.get("code") or item.get("stock_code")
        if symbol:
            symbols.append(symbol)

    return {
        "count": len(items),
        "active_count": active_count,
        "symbols": symbols,
        "notes": f"当前共有 {len(items)} 条策略，其中活跃策略 {active_count} 条",
    }


def summarize_candidates(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {
            "count": 0,
            "symbols": [],
            "notes": "当前无候选股票",
        }

    symbols: List[str] = []

    for item in items:
        symbol = item.get("symbol") or item.get("code") or item.get("stock_code")
        if symbol:
            symbols.append(symbol)

    return {
        "count": len(items),
        "symbols": symbols,
        "notes": f"当前共有 {len(items)} 条候选股票记录",
    }


def extract_trigger_symbol(trigger_event: Dict[str, Any] | None) -> str | None:
    if not trigger_event:
        return None

    for key in ("symbol", "code", "stock_code", "secCode"):
        value = trigger_event.get(key)
        if value:
            return str(value)

    return None


def build_context(
    workspace_dir: str | Path,
    trigger_reason: str = "manual_run",
    now: Optional[datetime] = None,
    mode: str = "scheduler",
    user_task: str = "",
    trigger_event: Optional[Dict[str, Any]] = None,
    related_symbol: str | None = None,
    recent_n: int = 5,
) -> RuntimeContext:
    workspace = Path(workspace_dir)
    now = now or datetime.now()

    mode = normalize_mode(mode)
    trigger_event = trigger_event or {}
    related_symbol = related_symbol or extract_trigger_symbol(trigger_event)

    state_dir = workspace / "state"
    pools_dir = workspace / "pools"
    logs_dir = workspace / "logs"

    account_state = read_json_file(state_dir / "account_state.json", default={})

    # 修改为实际总资产
    account_state["total_asset"] = account_state["total_asset"] - 1000000 + TURE_ASSET
    account_state["cash"] = account_state["cash"] - 1000000 + TURE_ASSET
    account_state["available_cash"] = account_state["available_cash"] - 1000000 + TURE_ASSET


    market_state = read_json_file(state_dir / "market_state.json", default={})

    holdings = read_jsonl_file(pools_dir / "holdings.jsonl")
    strategies = read_jsonl_file(pools_dir / "strategies.jsonl")
    candidates = read_jsonl_file(pools_dir / "candidates.jsonl")

    trades = read_jsonl_file(logs_dir / "trades.jsonl")
    events = read_jsonl_file(logs_dir / "events.jsonl")

    # trigger mode should focus on related symbol if present
    if mode == "trigger" and related_symbol:
        holdings_for_summary = filter_related_items(holdings, related_symbol)
        strategies_for_summary = filter_related_items(strategies, related_symbol)
        candidates_for_summary = filter_related_items(candidates, related_symbol)
        recent_trades = filter_related_items(trades, related_symbol)[-recent_n:]
        recent_events = filter_related_items(events, related_symbol)[-recent_n:]
    else:
        holdings_for_summary = holdings
        strategies_for_summary = strategies
        candidates_for_summary = candidates
        recent_trades = trades[-recent_n:]
        recent_events = events[-recent_n:]

    return RuntimeContext(
        now=now.strftime("%Y-%m-%d %H:%M:%S"),
        date=now.strftime("%Y-%m-%d"),
        weekday=WEEKDAY_MAP[now.weekday()],
        market_phase=detect_market_phase(now),
        mode=mode,
        trigger_reason=trigger_reason,
        user_task=user_task,
        trigger_event=trigger_event,
        account_state=account_state,
        market_state=market_state,
        holdings_summary=summarize_holdings(holdings_for_summary),
        strategies_summary=summarize_strategies(strategies_for_summary),
        candidates_summary=summarize_candidates(candidates_for_summary),
        recent_trades=recent_trades,
        recent_events=recent_events,
    )


def build_context_markdown(context: RuntimeContext) -> str:
    data = context.to_dict()

    def pretty_json(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2)

    user_task_block = ""
    if data.get("user_task"):
        user_task_block = f"""
## 2. 用户任务
{data["user_task"]}
"""

    trigger_event_block = ""
    if data.get("trigger_event"):
        trigger_event_block = f"""
## 3. 触发事件
```json
{pretty_json(data["trigger_event"])}
```
"""

    return f"""# 动态运行上下文

## 1. 当前调用信息
- 当前时间：{data["now"]}
- 当前日期：{data["date"]}
- 星期：{data["weekday"]}
- 当前市场阶段：{data["market_phase"]}
- 调用模式：{data["mode"]}
- 本次触发原因：{data["trigger_reason"]}
{user_task_block}{trigger_event_block}
## 4. 账户状态
```json
{pretty_json(data["account_state"])}
```

## 5. 市场状态
```json
{pretty_json(data["market_state"])}
```

## 6. 持仓摘要
```json
{pretty_json(data["holdings_summary"])}
```

## 7. 策略摘要
```json
{pretty_json(data["strategies_summary"])}
```

## 8. 候选股票摘要
```json
{pretty_json(data["candidates_summary"])}
```

## 9. 最近交易记录
```json
{pretty_json(data["recent_trades"])}
```

## 10. 最近事件记录
```json
{pretty_json(data["recent_events"])}
```

"""


if __name__ == "__main__":
    workspace_path = Path(__file__).resolve().parents[1] / "workspace"
    ctx = build_context(workspace_path, mode="scheduler", trigger_reason="manual_run")
    print(build_context_markdown(ctx))
