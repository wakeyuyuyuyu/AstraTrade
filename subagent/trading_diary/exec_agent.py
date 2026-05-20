from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WORKSPACE_DIR = PROJECT_ROOT / "workspace"
PROMPT_PATH = Path(__file__).with_name("prompt.md")
DEFAULT_OUTPUT_DIR = WORKSPACE_DIR / "diaries"


def read_markdown_file(path: Path) -> str:
    if not path.exists():
        return f"# Missing File\n\n文件不存在：{path.name}\n"
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


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
            except Exception:
                continue

            if isinstance(obj, dict):
                items.append(obj)

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


def normalize_date(value: str | None) -> str:
    if value and value.strip():
        raw = value.strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("--date 必须是 YYYY-MM-DD 格式") from exc

    return time.strftime("%Y-%m-%d", time.localtime())


def resolve_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    if not output_dir:
        return DEFAULT_OUTPUT_DIR

    path = Path(output_dir)
    if not path.is_absolute():
        path = project_root / path
    return path


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
        "trades_today": records_for_date(trades, target_date),
        "events_today": records_for_date(events, target_date),
    }


def render_prompt(project_root: Path, target_date: str, generated_at: str) -> str:
    base_prompt = read_markdown_file(project_root / "subagent" / "trading_diary" / "prompt.md")
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


def run_trading_diary(
    project_root: str | Path,
    target_date: str | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    from services.llm_service import call_llm

    root = Path(project_root).resolve()
    date = normalize_date(target_date)
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    prompt = render_prompt(root, date, generated_at)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "请根据输入上下文生成今天的炒股日记，只输出 Markdown 正文。"},
    ]

    diary = clean_markdown(call_llm(messages, "sub", temperature=0.4))
    output_path = resolve_output_dir(root, output_dir) / f"{date}.md"

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(diary, encoding="utf-8")

    return {
        "success": True,
        "date": date,
        "generated_at": generated_at,
        "output_file": str(output_path),
        "dry_run": dry_run,
        "bytes_written": 0 if dry_run else len(diary.encode("utf-8")),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate AstraTrade daily trading diary.")
    parser.add_argument("--mode", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--trigger-reason", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--extra-instructions", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--date",
        default=None,
        help="生成指定日期的日记，格式 YYYY-MM-DD；默认使用今天。",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR.relative_to(PROJECT_ROOT)),
        help="日记输出目录；相对路径基于项目根目录。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成并返回元信息，不写入 Markdown 文件。",
    )
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    result = run_trading_diary(
        project_root=PROJECT_ROOT,
        target_date=args.date,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
