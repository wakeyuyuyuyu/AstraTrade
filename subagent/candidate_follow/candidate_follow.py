from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CANDIDATES_PATH = PROJECT_ROOT / "workspace" / "pools" / "candidates.jsonl"
MX_DATA_SCRIPT = PROJECT_ROOT / "workspace" / "skills" / "mx-data" / "mx_data.py"
MX_DATA_OUTPUT_DIR = PROJECT_ROOT / "workspace" / "logs" / "mx_data" / "output"

OUTPUT_DIR = PROJECT_ROOT / "subagent" / "candidate_follow" / "candidate_state"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
            df[col] = df[col].apply(
                lambda x: x
                if isinstance(x, (dict, list))
                else ([] if col in {"tags", "evidence"} else {})
            )

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.zfill(6)

    return df


def safe_append_note(old_note: Any, new_note: str) -> str:
    old = "" if old_note is None else str(old_note).strip()
    if not old:
        return new_note
    return f"{old} | {new_note}"


def build_query(name: str) -> str:
    return f"{name}最新价"


def get_mx_data_output_path(query: str) -> Path:
    return MX_DATA_OUTPUT_DIR / f"mx_data_{query}.xlsx"


def run_mx_data_query(name: str) -> Path:
    """
    调用 mx-data 脚本查询股票最新价。

    等价命令：
    python workspace/skills/mx-data/mx_data.py "<name>最新价"

    脚本执行后，预期生成：
    workspace/logs/mx_data/output/mx_data_<name>最新价.xlsx
    """
    query = build_query(name)
    output_path = get_mx_data_output_path(query)

    if output_path.exists():
        output_path.unlink()

    command = [
        sys.executable,
        str(MX_DATA_SCRIPT.relative_to(PROJECT_ROOT)),
        query,
    ]

    print(f"执行查询: python workspace/skills/mx-data/mx_data.py \"{query}\"")

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if result.returncode != 0:
        raise RuntimeError(f"mx-data 查询失败，returncode={result.returncode}")

    time.sleep(5)

    if not output_path.exists():
        raise FileNotFoundError(f"mx-data 输出文件不存在: {output_path}")

    return output_path


def extract_latest_price_from_excel(path: Path) -> Optional[float]:
    """
    从 mx-data 输出 xlsx 中提取最新价。

    规则：
    - 优先读取列名为「最新价」的列
    - 如果找不到「最新价」，则回退读取第二列
    - 取该列第一条可转为数字的值
    """
    df = pd.read_excel(path)

    if df.empty:
        return None

    if "最新价" in df.columns:
        series = df["最新价"]
    elif len(df.columns) >= 2:
        series = df.iloc[:, 1]
    else:
        return None

    values = pd.to_numeric(series, errors="coerce").dropna()

    if values.empty:
        return None

    return float(values.iloc[0])


def fetch_latest_price_by_name(name: str) -> tuple[Optional[float], Optional[Path], Optional[str]]:
    """
    根据股票名称查询最新价。

    返回：
    - latest_price
    - output_path
    - error
    """
    try:
        output_path = run_mx_data_query(name)
        latest_price = extract_latest_price_from_excel(output_path)

        if latest_price is None:
            return None, output_path, "未能从 xlsx 中提取最新价"

        return latest_price, output_path, None

    except Exception as e:
        return None, None, str(e)


def save_update_snapshot(df: pd.DataFrame, time_str: str) -> Path:
    snapshot_path = OUTPUT_DIR / f"candidates_updated_{time_str}.json"

    records = json.loads(df.to_json(orient="records", force_ascii=False))
    with snapshot_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return snapshot_path


def update_candidates(time_str: str) -> pd.DataFrame:
    """
    同步候选池中已有股票的 current_price。

    流程：
    1. 读取 workspace/pools/candidates.jsonl
    2. 对每个候选股票读取 name
    3. 调用：
       python workspace/skills/mx-data/mx_data.py "<name>最新价"
    4. 等待 5 秒
    5. 读取：
       workspace/logs/mx_data/output/mx_data_<name>最新价.xlsx
    6. 从「最新价」列或第二列提取价格
    7. 更新 candidates.jsonl 中 current_price 和 updated_at

    注意：
    - 本函数只负责更新候选池中已有股票的信息。
    - 不判断 trigger。
    - 不唤醒主 Agent。
    - 不写 events。
    """
    old_candidates = read_candidates_jsonl(CANDIDATES_PATH)
    old_candidates = normalize_old_candidates(old_candidates)

    if old_candidates.empty:
        print("当前候选池为空，无需更新。")
        return old_candidates

    for idx, candidate in old_candidates.iterrows():
        symbol = str(candidate.get("symbol", "")).zfill(6)
        name = str(candidate.get("name", "")).strip()

        if not name:
            print(f"候选股票缺少 name，跳过，symbol={symbol}")
            old_candidates.loc[idx, "updated_at"] = str(time_str)
            old_candidates.loc[idx, "notes"] = safe_append_note(
                candidate.get("notes", ""),
                "候选股票缺少 name，未查询最新价",
            )
            continue

        latest_price, output_path, error = fetch_latest_price_by_name(name)

        if error:
            print(f"查询最新价失败，symbol={symbol}, name={name}, error={error}")
            old_candidates.loc[idx, "updated_at"] = str(time_str)
            old_candidates.loc[idx, "notes"] = safe_append_note(
                candidate.get("notes", ""),
                f"最新价查询失败: {error}",
            )
            continue

        old_candidates.loc[idx, "current_price"] = latest_price
        old_candidates.loc[idx, "updated_at"] = str(time_str)

        print(
            f"候选股票价格已更新: symbol={symbol}, name={name}, "
            f"current_price={latest_price}, source={output_path}"
        )

    old_candidates = normalize_old_candidates(old_candidates)

    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    old_candidates.to_json(
        CANDIDATES_PATH,
        orient="records",
        lines=True,
        force_ascii=False,
    )

    snapshot_path = save_update_snapshot(old_candidates, time_str.replace(":", "-"))
    print(f"候选池更新快照已保存: {snapshot_path}")

    return old_candidates


def main() -> None:
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    update_candidates(time_str)


if __name__ == "__main__":
    main()
