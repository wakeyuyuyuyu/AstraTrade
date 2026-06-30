"""持仓盯盘 Agent——加载 TRADING_RULES.md + 市场状态 + K线数据"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from services.llm_service import call_llm
from runtime.launcher import run_once
from subagent.holding_follow.holding_follow import update_holding


def read_markdown_file(path: Path) -> str:
    if not path.exists():
        return f"# Missing File\n\n文件不存在：{path.name}\n"
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    continue
    return items


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_model_output(text: str) -> Optional[Dict[str, Any]]:
    text = clean_json(text)
    if text.lower() == "null":
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return {"error_output": text}
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return {"error_output": text}


def read_market_context(project_root: Path) -> str:
    market = read_json(project_root / "workspace" / "state" / "market_state.json")
    if not market:
        return ""
    parts = []
    parts.append(f"market_view={market.get('market_view', 'unknown')}")
    parts.append(f"risk_level={market.get('risk_level', 'medium')}")
    score = market.get("market_sentiment", {}).get("score", 50)
    label = market.get("market_sentiment", {}).get("label", "neutral")
    parts.append(f"sentiment={score}({label})")
    hot = market.get("hot_topics", [])
    if hot:
        parts.append(f"hot_topics={','.join(hot)}")
    evidence = market.get("evidence", [])
    for e in evidence:
        s = e.get("summary", "")
        if "资金" in s or "北向" in s:
            parts.append(f"资金流向: {s}")
            break
    return "\n".join(parts)


def fetch_technical_data(project_root: Path, symbol: str, name: str) -> Dict[str, Any]:
    """查询个股K线技术指标，带重试。"""
    api_key = ""
    env_path = project_root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MX_APIKEY="):
                api_key = line.split("=", 1)[1].strip().strip("\"'")
                break
    if not api_key:
        api_key = "mkt_AEDMG5rTUWs0tzofjRPh12kTevGTlzInjmwrRBZJmJg"
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    queries = [
        f"{name}({symbol}) 今日技术指标 MA5 MA10 MA20 MACD KDJ RSI 成交量 收盘价 换手率 振幅",
        f"{name}({symbol}) 振幅",
    ]
    result: Dict[str, Any] = {}
    for attempt, q in enumerate(queries):
        try:
            if attempt > 0:
                time.sleep(2)
            body = {"toolQuery": q}
            resp = requests.post(url, headers=headers, json=body, timeout=15, verify=False)
            data = resp.json()
            for dto in data.get("data", {}).get("data", {}).get("searchDataResultDTO", {}).get("dataTableDTOList", []):
                if not isinstance(dto, dict):
                    continue
                table = dto.get("table", {})
                name_map = dto.get("nameMap", {})
                head = table.get("headName", [])
                if not isinstance(head, list) or not head:
                    continue
                for key in table:
                    if key == "headName":
                        continue
                    vals = table[key]
                    if isinstance(vals, list) and vals:
                        label = str(name_map.get(key, name_map.get(str(key), str(key))))
                        val = str(vals[0])
                        try:
                            result[label] = float(val.replace(",", "").replace("元", "").replace("%", ""))
                        except ValueError:
                            result[label] = val
        except Exception:
            pass
    return result


def render_prompts(project_root: str | Path, now_str: str) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    prompt_path = project_root / "subagent" / "holding_follow" / "prompt.md"
    trading_rules_path = project_root / "config" / "TRADING_RULES.md"
    holdings_path = project_root / "workspace" / "pools" / "holdings.jsonl"
    strategies_path = project_root / "workspace" / "pools" / "strategies.jsonl"

    base_prompt = read_markdown_file(prompt_path)
    trading_rules = read_markdown_file(trading_rules_path)
    market_ctx = read_market_context(project_root)

    if trading_rules and "文件不存在" not in trading_rules:
        base_prompt = base_prompt + "\n\n---\n## 当前交易规则\n\n以下规则从 config/TRADING_RULES.md 加载，请严格遵循：\n\n" + trading_rules
    if market_ctx:
        base_prompt = base_prompt + "\n\n---\n## 当前市场状态（实时数据）\n\n" + market_ctx

    holdings = read_jsonl(holdings_path)
    strategies = read_jsonl(strategies_path)
    strategy_map = {s.get("strategy_id"): s for s in strategies}

    tasks: List[Dict[str, Any]] = []
    for holding in holdings:
        if str(holding.get("status", "")).lower() != "holding":
            continue
        symbol = str(holding.get("symbol", "")).zfill(6)
        strategy_id = holding.get("strategy_id", "")
        strategy = strategy_map.get(strategy_id, {})

        name = holding.get("name", "")
        tech_data = fetch_technical_data(project_root, symbol, name)

        prompt = f"{base_prompt}\n\n## 当前时间\n\n{now_str}\n"
        if tech_data:
            prompt += "## 个股技术面数据（来自 mx-data）\n\n```\n"
            for k, v in tech_data.items():
                prompt += f"  {k}: {v}\n"
            prompt += "```\n\n"
        prompt += "## 持仓股票\n\n```json\n" + json.dumps(holding, ensure_ascii=False, indent=2) + "\n```\n\n"
        prompt += "## 关联策略\n\n```json\n" + json.dumps(strategy, ensure_ascii=False, indent=2) + "\n```\n"
        tasks.append({"symbol": symbol, "holding": holding, "strategy": strategy, "prompt": prompt})
    return tasks


def infer_exit_type(reason: str) -> str:
    r = reason.lower()
    if "stop_loss" in r or "止损" in reason:
        return "stop_loss"
    if "take_profit" in r or "止盈" in reason or "target" in r:
        return "take_profit"
    if "expired" in r or "过期" in reason:
        return "strategy_expired"
    if "死叉" in reason or "死叉" in reason or "ma5" in r:
        return "technical_exit"
    if "资金" in reason:
        return "fund_flow_exit"
    return "condition_exit"


def build_trigger_event(project_root: Path, task: Dict[str, Any], model_output: Dict[str, Any], now_str: str) -> Dict[str, Any]:
    holding = task["holding"]
    reason = str(model_output.get("reason", ""))
    return {
        "source": "holding_follow",
        "trigger_type": infer_exit_type(reason),
        "symbol": task["symbol"],
        "name": holding.get("name", ""),
        "strategy_id": model_output.get("strategy_id") or holding.get("strategy_id") or "",
        "reason": reason,
        "observed": {"current_price": holding.get("current_price"), "unrealized_pnl_pct": holding.get("unrealized_pnl_pct"), "status": holding.get("status")},
        "holding_snapshot": holding,
        "timestamp": now_str,
    }


def run_holding_follow(project_root: str | Path, update_before_check: bool = True, wake_main_agent: bool = True, max_steps: int = 30) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if update_before_check:
        update_holding(now_str)
    tasks = render_prompts(project_root, now_str)
    results: List[Dict[str, Any]] = []
    events_path = project_root / "workspace" / "logs" / "events.jsonl"

    for task in tasks:
        messages = [{"role": "system", "content": task["prompt"]}, {"role": "user", "content": "请严格按协议输出 JSON。"}]
        response = call_llm(messages, "sub")
        parsed = parse_model_output(response)
        record = {"timestamp": now_str, "source": "holding_follow", "symbol": task["symbol"], "strategy_id": task.get("strategy", {}).get("strategy_id", ""), "triggered": False, "model_output": parsed}
        if parsed is None:
            results.append(record)
            continue
        if "error_output" in parsed:
            record["error"] = "model_output_parse_failed"
            results.append(record)
            continue
        sid = parsed.get("strategy_id")
        reason = parsed.get("reason")
        if not sid or not reason:
            record["error"] = "missing_strategy_id_or_reason"
            results.append(record)
            continue
        trigger_event = build_trigger_event(project_root, task, parsed, now_str)
        record["triggered"] = True
        record["trigger_event"] = trigger_event
        append_jsonl(events_path, {
            "timestamp": now_str, "source": "holding_follow", "event_type": "subagent_trigger",
            "symbol": trigger_event["symbol"], "name": trigger_event.get("name", ""),
            "strategy_id": trigger_event.get("strategy_id", ""), "candidate_id": "",
            "trigger_type": trigger_event.get("trigger_type", ""), "reason": trigger_event.get("reason", ""),
            "trigger_event": trigger_event,
        })
        if wake_main_agent:
            main_result = run_once(project_root=project_root, mode="trigger", trigger_reason="holding_follow_trigger", trigger_event=trigger_event,
                extra_instructions="本轮由 holding_follow 子 Agent 触发。请只处理 trigger_event 相关持仓，先核验条件，再决定是否执行卖出。", max_steps=max_steps)
            record["main_agent_result"] = main_result
        results.append(record)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run holding follow subagent.")
    parser.add_argument("--no-update", action="store_true", help="不先同步持仓行情")
    parser.add_argument("--dry-run", action="store_true", help="只判断是否触发，不唤醒主 Agent")
    parser.add_argument("--max-steps", type=int, default=30, help="唤醒主 Agent 后的最大执行步数")
    return parser


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    args = build_arg_parser().parse_args()
    results = run_holding_follow(project_root=project_root, update_before_check=not args.no_update, wake_main_agent=not args.dry_run, max_steps=args.max_steps)
    print(json.dumps(results, ensure_ascii=False, indent=2))
