from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()

MX_APIKEY = os.environ.get("MX_APIKEY")
MX_API_URL = os.environ.get("MX_API_URL")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "subagent" / "candidate_follow" / "candidate_state"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def check_apikey() -> None:
    """检查 API 密钥和行情接口是否配置。"""
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
        else:
            print("\n操作结果: 失败")
            print(f"错误码: {result.get('code')}")
            print(f"错误信息: {result.get('message')}")

        return output_path

    except Exception as e:
        print(f"网络请求失败: {str(e)}")
        sys.exit(1)


def ask_candidate_quote(symbol: str, name: str, time_str: str) -> Path:
    """
    请求单只候选股票的行情信息。

    不同 MX 行情接口的 body 可能不同。
    如果你的实际接口字段不同，只需要修改这里。
    """
    body = {
        "symbol": symbol,
        "secCode": symbol,
        "name": name,
        "moneyUnit": 1,
    }

    return make_request(
        "/api/claw/mockTrading/positions",
        body,
        output_prefix=f"candidate_{symbol}",
        time_str=time_str,
    )


def read_candidates_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(
            columns=[
                "candidate_id",
                "symbol",
                "name",
                "reason",
                "source",
                "tags",
                "score",
                "status",
                "current_price",
                "trigger",
                "buy_plan",
                "risk",
                "valid_until",
                "added_at",
                "updated_at",
                "evidence",
                "next_action",
                "notes",
            ]
        )

    return pd.read_json(
        path,
        lines=True,
        dtype={
            "candidate_id": str,
            "symbol": str,
            "name": str,
            "source": str,
            "status": str,
            "valid_until": str,
            "added_at": str,
            "updated_at": str,
        },
    )


def normalize_old_candidates(df: pd.DataFrame) -> pd.DataFrame:
    str_cols = [
        "candidate_id",
        "symbol",
        "name",
        "reason",
        "source",
        "status",
        "valid_until",
        "added_at",
        "updated_at",
        "next_action",
        "notes",
    ]
    float_cols = ["score", "current_price"]
    object_cols = ["tags", "trigger", "buy_plan", "risk", "evidence"]

    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)

    for col in object_cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x if isinstance(x, (dict, list)) else ([] if col in {"tags", "evidence"} else {}))

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.zfill(6)

    return df


def deep_find_number(obj: Any, keys: set[str]) -> Optional[float]:
    """
    从不确定的行情返回结构中提取价格字段。

    支持常见字段：
    - price
    - current_price
    - currentPrice
    - latest_price
    - latestPrice
    - lastPrice
    - close
    - newPrice
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                try:
                    return float(value)
                except Exception:
                    pass

        for value in obj.values():
            found = deep_find_number(value, keys)
            if found is not None:
                return found

    if isinstance(obj, list):
        for item in obj:
            found = deep_find_number(item, keys)
            if found is not None:
                return found

    return None


def extract_current_price(raw_data: Dict[str, Any]) -> Optional[float]:
    price_keys = {
        "price",
        "current_price",
        "currentPrice",
        "latest_price",
        "latestPrice",
        "lastPrice",
        "close",
        "newPrice",
    }

    return deep_find_number(raw_data, price_keys)


def update_candidates(time_str: str) -> pd.DataFrame:
    """
    从行情接口同步候选池股票信息到 workspace/pools/candidates.jsonl。

    注意：
    - 本函数只负责更新候选池中已有股票的信息。
    - 不判断 trigger。
    - 不唤醒主 Agent。
    - 不写 events。
    """
    candidates_path = PROJECT_ROOT / "workspace" / "pools" / "candidates.jsonl"

    old_candidates = read_candidates_jsonl(candidates_path)
    old_candidates = normalize_old_candidates(old_candidates)

    if old_candidates.empty:
        print("当前候选池为空，无需更新。")
        return old_candidates

    for idx, candidate in old_candidates.iterrows():
        symbol = str(candidate.get("symbol", "")).zfill(6)
        name = str(candidate.get("name", ""))

        if not symbol:
            continue

        raw_path = ask_candidate_quote(symbol, name, time_str)

        with raw_path.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)

        current_price = extract_current_price(raw_data)

        if current_price is None:
            print(f"未能从行情返回中提取价格，symbol={symbol}")
            old_candidates.loc[idx, "updated_at"] = str(time_str)
            old_candidates.loc[idx, "notes"] = f"{candidate.get('notes', '')} | 行情已请求但未提取到价格"
            continue

        old_candidates.loc[idx, "current_price"] = current_price
        old_candidates.loc[idx, "updated_at"] = str(time_str)

    old_candidates = normalize_old_candidates(old_candidates)

    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    old_candidates.to_json(
        candidates_path,
        orient="records",
        lines=True,
        force_ascii=False,
    )

    return old_candidates


def main() -> None:
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    update_candidates(time_str)


if __name__ == "__main__":
    main()
