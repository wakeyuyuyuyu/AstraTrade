from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WORKSPACE_DIR = PROJECT_ROOT / "workspace"
MEMORY_DIR = PROJECT_ROOT / "memory"
PROMPT_PATH = Path(__file__).with_name("prompt.md")
DEFAULT_OUTPUT_DIR = WORKSPACE_DIR / "diaries"


def read_markdown_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
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


def record_timestamp(record: Dict[str, Any]) -> str:
    for key in ("timestamp", "updated_at", "created_at", "added_at", "opened_at"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def records_for_date(items: List[Dict[str, Any]], target_date: str) -> List[Dict[str, Any]]:
    return [
        item
        for item in items
        if record_timestamp(item).startswith(target_date)
    ]


def load_recent_memories(days: int = 7) -> List[Dict[str, str]]:
    today = datetime.now()
    memories: List[Dict[str, str]] = []

    for offset in range(1, days + 1):
        date_str = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        mem_path = MEMORY_DIR / date_str / "eod_review.md"
        content = read_markdown_file(mem_path)
        if content:
            memories.append({"date": date_str, "content": content})

    return memories


def build_context(project_root: Path, target_date: str, generated_at: str) -> Dict[str, Any]:
    workspace = project_root / "workspace"

    trades = read_jsonl(workspace / "logs" / "trades.jsonl")
    events = read_jsonl(workspace / "logs" / "events.jsonl")

    return {
        "date": target_date,
        "generated_at": generated_at,
        "account_state": read_json(workspace / "state" / "account_state.json"),
        "market_state": read_json(workspace / "state" / "market_state.json"),
        "holdings": read_jsonl(workspace / "pools" / "holdings.jsonl"),
        "strategies": read_jsonl(workspace / "pools" / "strategies.jsonl"),
        "candidates": read_jsonl(workspace / "pools" / "candidates.jsonl"),
        "trades": trades,
        "trades_today": records_for_date(trades, target_date),
        "events_today": records_for_date(events, target_date),
        "recent_memories": load_recent_memories(days=7),
    }


def render_prompt(project_root: Path, target_date: str, generated_at: str) -> str:
    base_prompt = read_markdown_file(project_root / "subagent" / "eod_review" / "prompt.md")
    if not base_prompt:
        base_prompt = "# EOD 复盘总结\n\n默认提示词缺失。"
    context = build_context(project_root, target_date, generated_at)

    return (
        f"{base_prompt}\n\n"
        "## 生成日期\n\n"
        f"{target_date}\n\n"
        "## 当前生成时间\n\n"
        f"{generated_at}\n\n"
        "## 输入上下文\n\n"
        "```json\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n"
        "```\n"
    )


def clean_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text.rstrip() + "\n"


def resolve_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    if not output_dir:
        return PROJECT_ROOT / "memory"
    path = Path(output_dir)
    if not path.is_absolute():
        path = project_root / path
    return path


def run_eod_review(
    project_root: str | Path,
    target_date: str | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    from services.llm_service import call_llm

    root = Path(project_root).resolve()
    date = target_date or datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt = render_prompt(root, date, generated_at)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": (
                "请根据以上输入上下文，生成今天（{date}）的完整收盘复盘总结，"
                "只输出 Markdown 正文。"
            ).format(date=date),
        },
    ]

    review = clean_markdown(call_llm(messages, "sub", temperature=0.3))
    output_path = resolve_output_dir(root, output_dir) / date / "eod_review.md"

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(review, encoding="utf-8")

    return {
        "success": True,
        "date": date,
        "generated_at": generated_at,
        "output_file": str(output_path),
        "dry_run": dry_run,
        "bytes_written": 0 if dry_run else len(review.encode("utf-8")),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate AstraTrade EOD review summary.")
    parser.add_argument("--mode", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--trigger-reason", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--extra-instructions", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--date",
        default=None,
        help="生成指定日期的复盘，格式 YYYY-MM-DD；默认使用今天。",
    )
    parser.add_argument(
        "--output-dir",
        default=str(MEMORY_DIR.relative_to(PROJECT_ROOT)),
        help="输出目录；相对路径基于项目根目录。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成并返回元信息，不写入 Markdown 文件。",
    )
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    result = run_eod_review(
        project_root=PROJECT_ROOT,
        target_date=args.date,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
