from __future__ import annotations

import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

MX_DATA_PATH = PROJECT_ROOT / "workspace" / "skills" / "mx-data" / "mx_data.py"
spec = importlib.util.spec_from_file_location("mx_data", MX_DATA_PATH)
mx_data_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mx_data_module)
MXData = mx_data_module.MXData

from services.llm_service import call_llm

RULES_PATH = PROJECT_ROOT / "config" / "SCREENING_RULES.md"
PROMPT_PATH = PROJECT_ROOT / "subagent" / "stock_scout" / "prompt.md"
RECOMMEND_PATH = PROJECT_ROOT / "workspace" / "pools" / "scout_recommendations.jsonl"
CANDIDATES_PATH = PROJECT_ROOT / "workspace" / "pools" / "candidates.jsonl"
MARKET_STATE_PATH = PROJECT_ROOT / "workspace" / "state" / "market_state.json"
OUTPUT_DIR = PROJECT_ROOT / "workspace" / "logs" / "stock_scout"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_market_context() -> str:
    market = read_json(MARKET_STATE_PATH)
    if not market:
        return ""
    parts = []
    parts.append(f"当前市场状态: {market.get('market_view', 'unknown')}")
    parts.append(f"风险等级: {market.get('risk_level', 'medium')}")
    score = market.get("market_sentiment", {}).get("score", 50)
    label = market.get("market_sentiment", {}).get("label", "neutral")
    parts.append(f"情绪评分: {score}/100 ({label})")
    hot = market.get("hot_topics", [])
    if hot:
        parts.append(f"热门板块: {', '.join(hot)}")
    watch = market.get("watch_sectors", [])
    if watch:
        parts.append(f"关注板块: {', '.join(watch)}")
    avoid = market.get("avoid_sectors", [])
    if avoid:
        parts.append(f"回避板块: {', '.join(avoid)}")
    events = market.get("key_events", [])
    if events:
        parts.append(f"今日重要新闻({len(events)}条): " + " | ".join(e[:60] for e in events[:5]))
    return "\n".join(parts)


def read_rules() -> str:
    rules = RULES_PATH.read_text(encoding="utf-8").strip()
    base = PROMPT_PATH.read_text(encoding="utf-8").strip()
    context = read_market_context()
    if context:
        return f"{base}\n\n## 当前市场环境\n\n以下数据来自实时市场状态：\n\n{context}\n\n{rules}"
    return f"{base}\n\n{rules}"


def read_recommendations() -> list[dict]:
    if not RECOMMEND_PATH.exists() or RECOMMEND_PATH.stat().st_size == 0:
        return []
    items = []
    with open(RECOMMEND_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    return items


def write_recommendations(items: list[dict]) -> None:
    RECOMMEND_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECOMMEND_PATH, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def symbol_exists(symbol: str, recs: list[dict]) -> bool:
    return any(
        r.get("symbol", "").zfill(6) == symbol and r.get("status") == "pending"
        for r in recs
    )


def candidate_symbol_exists(symbol: str) -> bool:
    if not CANDIDATES_PATH.exists() or CANDIDATES_PATH.stat().st_size == 0:
        return False
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    if obj.get("symbol", "").zfill(6) == symbol:
                        return True
                except Exception:
                    continue
    return False


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


def ask_llm_for_stocks(fundamentals_map: dict = None) -> list[dict]:
    system_prompt = read_rules()
    user_msg = "请根据选股规则，推荐 3~5 只当前符合条件的 A 股标的，输出评分JSON数组。"
    if fundamentals_map:
        user_msg += "\n\n以下为部分候选个股的实时金融数据，可用于辅助评分：\n"
        for sym, data in list(fundamentals_map.items())[:20]:
            items = " | ".join([f"{k}={v}" for k, v in list(data.items())[:10]])
            user_msg += f"  {sym}: {items}\n"
        user_msg += "\n优先从上面的数据中选择评分高的标的。"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    response = call_llm(messages, "main")
    cleaned = clean_json(response)
    try:
        stocks = json.loads(cleaned)
        if isinstance(stocks, dict):
            stocks = [stocks]
        return stocks if isinstance(stocks, list) else []
    except json.JSONDecodeError:
        return []


def _extract_pivot(table: dict, name_map: dict) -> dict:
    """从 mx-data pivot 格式中提取最新值。"""
    result: dict = {}
    head = table.get("headName", [])
    if not isinstance(head, list) or not head:
        return result
    for key in table:
        if key == "headName":
            continue
        vals = table[key]
        if isinstance(vals, list) and vals:
            label = str(name_map.get(key, name_map.get(str(key), str(key))))
            val = str(vals[0])
            result[label] = val
    return result


def query_mx_fundamentals(symbol: str, name: str) -> dict:
    """分字段查询所有基本面+估值+股东+分红+流动性数据。"""
    result: dict = {}
    single_fields = [
        "最新价", "市盈率PE(TTM)", "市净率PB", "总市值",
        "ROE", "毛利率", "净利润同比增长", "资产负债率",
        "股息率",
    ]
    special_queries = [
        ("换手率 成交额", ["换手率", "成交额"]),
        ("大股东质押比例", ["大股东质押比例"]),
        ("前十大股东 持股比例", ["前十大股东持股比例"]),
        ("机构持股比例", ["机构持股比例"]),
        ("经营性现金流", ["经营性现金流"]),
    ]

    try:
        mx = MXData()
        # round 1: 单字段逐个查询（最可靠，避免组合查询失败）
        for field in single_fields:
            try:
                q = f"{name}({symbol}) {field}"
                r = mx.query(q)
                for dto in r.get("data", {}).get("data", {}).get("searchDataResultDTO", {}).get("dataTableDTOList", []):
                    if not isinstance(dto, dict):
                        continue
                    extracted = _extract_pivot(dto.get("table", {}), dto.get("nameMap", {}))
                    result.update(extracted)
                time.sleep(0.5)  # 查询间隔，避免限流
            except Exception:
                continue

        # round 2: 简单组合查询（换手率/成交额/质押等）
        for query_suffix, expected_labels in special_queries:
            try:
                q = f"{name}({symbol}) {query_suffix}"
                r = mx.query(q)
                for dto in r.get("data", {}).get("data", {}).get("searchDataResultDTO", {}).get("dataTableDTOList", []):
                    if not isinstance(dto, dict):
                        continue
                    extracted = _extract_pivot(dto.get("table", {}), dto.get("nameMap", {}))
                    result.update(extracted)
                time.sleep(0.5)
            except Exception:
                continue
    except Exception as e:
        print(f"    mx-data 综合查询失败: {e}")

    return result


def extract_price_from_mx(mx_result: dict) -> float:
    try:
        inner = mx_result.get("data", {}).get("data", {})
        search = inner.get("searchDataResultDTO", {})
        for dto in search.get("dataTableDTOList", []):
            table = dto.get("table", {})
            name_map = dto.get("nameMap", {})
            if not table:
                continue
            head = table.get("headName", [])
            if not isinstance(head, list) or not head:
                continue
            for key in table:
                if key == "headName":
                    continue
                label = str(name_map.get(key, name_map.get(str(key), "")))
                vals = table[key]
                if isinstance(vals, list) and vals:
                    val_str = str(vals[0])
                    try:
                        cleaned = val_str.replace(",", "").replace("元", "").strip()
                        parsed = float(cleaned)
                        if label in ("最新价", "收盘价", "currentPrice") or ("价" in label):
                            if 0.1 < parsed < 10000:
                                return parsed
                        if 0.1 < parsed < 10000:
                            return parsed
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass
    return 0.0


def add_to_candidates(symbol: str, name: str, reason: str, score: int, trigger_type: str, trigger_price_offset: float, now_str: str, fundamentals: dict = None) -> None:
    initial_price = 0.0
    if fundamentals:
        for k, v in fundamentals.items():
            if "价" in k or "price" in k.lower():
                try:
                    p = float(v.replace(",", "").replace("元", ""))
                    if 0 < p < 10000:
                        initial_price = p
                        break
                except: pass
    if initial_price <= 0:
        try:
            mx = MXData()
            result = mx.query(f"{name}({symbol}) 最新价 收盘价")
            initial_price = extract_price_from_mx(result)
        except Exception:
            pass
    if initial_price <= 0:
        initial_price = 10.0

    trigger_price = round(initial_price * trigger_price_offset, 2)
    if trigger_type == "price_below":
        condition = f"价格回调至{trigger_price}元以下时买入"
    elif trigger_type == "pullback":
        condition = f"回踩至{trigger_price}元附近企稳时买入"
    else:
        condition = f"价格达到{trigger_price}元时买入"

    stop_loss = round(initial_price * 0.88, 2)
    take_profit = round(initial_price * 1.25, 2)

    candidate = {
        "candidate_id": f"AUTO-{now_str[:10].replace('-', '')}-{uuid.uuid4().hex[:6]}",
        "symbol": symbol.zfill(6),
        "name": name,
        "reason": reason,
        "source": "stock_scout",
        "tags": [],
        "score": score,
        "status": "ready",
        "current_price": initial_price,
        "trigger": {"type": trigger_type, "price": trigger_price, "condition": condition},
        "buy_plan": {"planned_quantity": 0, "planned_cash": 0, "max_position_ratio": 0.5},
        "risk": {"stop_loss_price": stop_loss, "take_profit_price": take_profit},
        "valid_until": "",
        "added_at": now_str,
        "updated_at": now_str,
        "evidence": [{"source": "stock_scout", "summary": reason}],
        "next_action": condition,
        "notes": f"自动选股推荐(评分{score}): {reason}",
    }

    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    print(f"    => 已自动加入候选池(评分{score}, {trigger_type}@{trigger_price}, 当前价{initial_price})")


def run_scout() -> list[dict]:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    existing = read_recommendations()

    # Step 0: 先查询一批常见蓝筹/高评分个股的金融数据，注入 LLM 辅助评分
    default_symbols = [
        ("600887", "伊利股份"), ("000651", "格力电器"), ("600519", "贵州茅台"),
        ("000333", "美的集团"), ("601318", "中国平安"), ("600036", "招商银行"),
        ("002415", "海康威视"), ("600309", "万华化学"), ("000858", "五粮液"),
        ("600690", "海尔智家"), ("002714", "牧原股份"), ("601166", "兴业银行"),
        ("000002", "万科A"), ("600585", "海螺水泥"), ("002304", "洋河股份"),
    ]
    fundamentals_map: dict = {}
    for sym, nam in default_symbols:
        try:
            fd = query_mx_fundamentals(sym, nam)
            if fd:
                fundamentals_map[sym] = fd
        except Exception:
            pass

    print("Step 1: LLM 推荐候选股（已注入金融数据）...")
    stocks = ask_llm_for_stocks(fundamentals_map)
    if not stocks:
        print("LLM 未返回有效推荐")
        return []

    print(f"LLM 推荐了 {len(stocks)} 只股票")
    results = []
    new_recs = []

    for stock in stocks:
        symbol = str(stock.get("symbol", "")).zfill(6)
        name = stock.get("name", "")
        reason = stock.get("reason", "")
        score = int(stock.get("score", 0))
        trigger_type = stock.get("trigger_type", "price_below")
        trigger_offset = float(stock.get("trigger_price_offset", 0.95))

        if not symbol or not name:
            continue

        if symbol_exists(symbol, existing):
            print(f"  跳过 {symbol} {name}：已有待确认推荐")
            results.append({"symbol": symbol, "name": name, "status": "已存在推荐"})
            continue

        if candidate_symbol_exists(symbol):
            print(f"  跳过 {symbol} {name}：已在候选池中")
            results.append({"symbol": symbol, "name": name, "status": "已在候选池"})
            continue

        print(f"  验证 {symbol} {name}...")
        # 查询综合金融数据（如果不在预查列表中）
        fundamentals = fundamentals_map.get(symbol)
        if not fundamentals:
            fundamentals = query_mx_fundamentals(symbol, name)

        if score >= 75:
            add_to_candidates(symbol, name, reason, score, trigger_type, trigger_offset, now_str, fundamentals)
            print(f"    + 已直接加入候选池(评分{score}≥75)")
            results.append({"symbol": symbol, "name": name, "status": "自动加入候选", "score": score})
        else:
            rec_id = f"REC-{now_str[:10].replace('-', '')}-{uuid.uuid4().hex[:6]}"
            recommendation = {
                "id": rec_id,
                "symbol": symbol,
                "name": name,
                "reason": reason,
                "score": score,
                "trigger_type": trigger_type,
                "trigger_price_offset": trigger_offset,
                "fundamentals": {k: v for k, v in (fundamentals or {}).items() if not k.startswith("mx_")},
                "status": "pending",
                "recommended_at": now_str,
            }
            new_recs.append(recommendation)
            print(f"    + 已加入待确认推荐(评分{score}<75)")
            results.append({"symbol": symbol, "name": name, "status": "待确认", "score": score})

    if new_recs:
        all_recs = existing + new_recs
        write_recommendations(all_recs)
        print(f"\n共 {len(new_recs)} 条待确认推荐")

    try:
        report_path = OUTPUT_DIR / f"scout_{now_str.replace(':', '-')}.json"
        report_path.write_text(json.dumps({"timestamp": now_str, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="自动选股子Agent")
    args = parser.parse_args()
    results = run_scout()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
