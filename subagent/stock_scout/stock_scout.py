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

RULES_PATH = PROJECT_ROOT / "subagent" / "stock_scout" / "SCREENING_RULES.md"
PROMPT_PATH = PROJECT_ROOT / "subagent" / "stock_scout" / "prompt.md"
RECOMMEND_PATH = PROJECT_ROOT / "workspace" / "pools" / "scout_recommendations.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "workspace" / "logs" / "stock_scout"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def read_rules() -> str:
    rules = RULES_PATH.read_text(encoding="utf-8").strip()
    base = PROMPT_PATH.read_text(encoding="utf-8").strip()
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


def ask_llm_for_stocks() -> list[dict]:
    system_prompt = read_rules()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请根据选股规则，推荐 3~5 只当前符合条件的 A 股标的，输出 JSON 数组。"},
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


def verify_stock_with_mx(symbol: str, name: str) -> dict | None:
    try:
        mx = MXData()
        query = f"{name} 最新价 市盈率PE(TTM) 市净率PB 总市值 ROE 净利润同比增长 毛利率"
        result = mx.query(query)
        return result
    except Exception as e:
        print(f"    mx-data 查询失败: {e}")
        return None


def run_scout() -> list[dict]:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    existing = read_recommendations()

    print("Step 1: LLM 推荐候选股...")
    stocks = ask_llm_for_stocks()
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

        if not symbol or not name:
            continue

        if symbol_exists(symbol, existing):
            print(f"  跳过 {symbol} {name}：已有待确认推荐")
            results.append({"symbol": symbol, "name": name, "status": "已存在"})
            continue

        print(f"  验证 {symbol} {name}...")
        mx_result = verify_stock_with_mx(symbol, name)
        if mx_result is None:
            print(f"    mx-data 查询失败，跳过")
            results.append({"symbol": symbol, "name": name, "status": "数据查询失败"})
            continue

        rec_id = f"REC-{now_str[:10].replace('-', '')}-{uuid.uuid4().hex[:6]}"
        recommendation = {
            "id": rec_id,
            "symbol": symbol,
            "name": name,
            "reason": reason,
            "mx_data_preview": str(mx_result)[:500],
            "status": "pending",
            "recommended_at": now_str,
        }
        new_recs.append(recommendation)
        print(f"    + 已加入待确认推荐")
        results.append({"symbol": symbol, "name": name, "status": "待确认"})

    if new_recs:
        all_recs = existing + new_recs
        write_recommendations(all_recs)
        print(f"\n共 {len(new_recs)} 条新推荐，等待用户确认")

    try:
        report = {
            "timestamp": now_str,
            "total_recommended": len(stocks),
            "new_recommendations": len(new_recs),
            "results": results,
        }
        report_path = OUTPUT_DIR / f"scout_{now_str.replace(':', '-')}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已保存: {report_path}")
    except Exception as e:
        print(f"保存报告失败: {e}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="自动选股子Agent")
    args = parser.parse_args()
    results = run_scout()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
