from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()

MX_APIKEY = os.environ.get("MX_APIKEY")
MX_API_URL = os.environ.get("MX_API_URL")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "subagent" / "holding_follow" / "holding_state"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def check_apikey() -> None:
    """检查 API 密钥是否配置。"""
    if not MX_APIKEY:
        print("错误: 未配置 MX_APIKEY 环境变量，请先配置 API 密钥")
        print("示例: export MX_APIKEY=your_api_key_here")
        sys.exit(1)

    if not MX_API_URL:
        print("错误: 未配置 MX_API_URL 环境变量，请先配置 API 地址")
        sys.exit(1)


def make_request(endpoint: str, body: Dict[str, Any], output_prefix: str, time_str: str) -> Path:
    """发送 POST 请求并保存结果。"""
    check_apikey()

    full_url = f"{MX_API_URL}{endpoint}"
    headers = {
        "apikey": MX_APIKEY,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(full_url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        result = response.json()

        output_path = OUTPUT_DIR / f"{output_prefix}_{time_str}.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"请求完成，结果保存在 {output_path}")

        if result.get("success") or str(result.get("code")) == "200":
            print("\n操作结果: 成功")
            if "message" in result:
                print(f"提示信息: {result['message']}")

            data = result.get("data")
            if isinstance(data, dict):
                if "totalAssets" in data:
                    print("\n账户资金:")
                    print(f"  总资产: {data.get('totalAssets', 0):.2f} 元")
                    print(f"  可用资金: {data.get('availBalance', 0):.2f} 元")
                if "orderId" in data:
                    print("\n委托成功:")
                    print(f"  委托编号: {data['orderId']}")
        else:
            print("\n操作结果: 失败")
            print(f"错误码: {result.get('code')}")
            print(f"错误信息: {result.get('message')}")

        return output_path

    except Exception as e:
        print(f"网络请求失败: {str(e)}")
        sys.exit(1)


def ask_holding(time_str: str) -> Path:
    """请求持仓信息。"""
    return make_request(
        "/api/claw/mockTrading/positions",
        {"moneyUnit": 1},
        output_prefix="holding",
        time_str=time_str,
    )


def read_holdings_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(
            columns=[
                "holding_id",
                "symbol",
                "name",
                "count",
                "availCount",
                "cost_price",
                "current_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "strategy_id",
                "status",
                "opened_at",
                "updated_at",
                "notes",
            ]
        )

    return pd.read_json(
        path,
        lines=True,
        dtype={
            "holding_id": str,
            "symbol": str,
            "strategy_id": str,
            "opened_at": str,
            "updated_at": str,
        },
    )


def normalize_old_holdings(df: pd.DataFrame) -> pd.DataFrame:
    str_cols = ["holding_id", "symbol", "name", "strategy_id", "status", "opened_at", "updated_at", "notes"]
    float_cols = ["cost_price", "current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct"]
    int_cols = ["count", "availCount"]

    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)

    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


def update_holding(time_str: str) -> pd.DataFrame:
    """
    从模拟交易接口同步持仓到 workspace/pools/holdings.jsonl。

    注意：
    - 本函数只负责同步持仓状态。
    - 是否触发交易条件由 exec_agent.py 判断。
    """
    raw_path = ask_holding(time_str)

    with raw_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    data = raw_data.get("data") or {}
    new_holdings = data.get("posList") or []

    holdings_path = PROJECT_ROOT / "workspace" / "pools" / "holdings.jsonl"
    old_holdings = read_holdings_jsonl(holdings_path)
    old_holdings = normalize_old_holdings(old_holdings)

    for holding in new_holdings:
        symbol = str(holding.get("secCode", "")).zfill(6)
        if not symbol:
            continue

        cost_price = holding.get("costPrice", 0) / (10 ** holding.get("costPriceDec", 0))
        current_price = holding.get("price", 0) / (10 ** holding.get("priceDec", 0))
        market_value = holding.get("value", 0)
        count = int(holding.get("count", 0))
        avail_count = int(holding.get("availCount", 0))

        unrealized_pnl = (current_price - cost_price) * count
        unrealized_pnl_pct = current_price / cost_price - 1 if cost_price else 0

        if "symbol" in old_holdings.columns and symbol in old_holdings["symbol"].values:
            idx = old_holdings["symbol"] == symbol
            old_holdings.loc[idx, "cost_price"] = cost_price
            old_holdings.loc[idx, "current_price"] = current_price
            old_holdings.loc[idx, "market_value"] = market_value
            old_holdings.loc[idx, "unrealized_pnl"] = unrealized_pnl
            old_holdings.loc[idx, "unrealized_pnl_pct"] = unrealized_pnl_pct
            old_holdings.loc[idx, "count"] = count
            old_holdings.loc[idx, "availCount"] = avail_count
            old_holdings.loc[idx, "updated_at"] = str(time_str)
        else:
            new_line = pd.DataFrame(
                {
                    "holding_id": [f"{symbol}_{time_str}"],
                    "symbol": [symbol],
                    "name": [holding.get("secName", "")],
                    "count": [count],
                    "availCount": [avail_count],
                    "cost_price": [cost_price],
                    "current_price": [current_price],
                    "market_value": [market_value],
                    "unrealized_pnl": [unrealized_pnl],
                    "unrealized_pnl_pct": [unrealized_pnl_pct],
                    "strategy_id": [""],
                    "status": [holding.get("posStatus", "holding")],
                    "opened_at": [str(time_str)],
                    "updated_at": [str(time_str)],
                    "notes": ["Agent未同步，手动新增持仓股票"],
                }
            )
            old_holdings = pd.concat([old_holdings, new_line], ignore_index=True)

    old_holdings = normalize_old_holdings(old_holdings)

    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    old_holdings.to_json(
        holdings_path,
        orient="records",
        lines=True,
        force_ascii=False,
    )

    return old_holdings


def main() -> None:
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    update_holding(time_str)


if __name__ == "__main__":
    main()
