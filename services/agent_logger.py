from __future__ import annotations

import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Any


_LOG_DIR: Path | None = None


def _ensure_log_dir() -> Path:
    global _LOG_DIR
    if _LOG_DIR is None:
        root = Path(__file__).resolve().parents[1]
        _LOG_DIR = root / "workspace" / "logs" / "agent_actions"
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def _today_log() -> Path:
    return _ensure_log_dir() / f"{datetime.now().strftime('%Y-%m-%d')}.log"


def log_file_path() -> Path:
    return _today_log()


def _write(msg: str) -> None:
    log_path = _today_log()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def log(source: str, action: str, detail: str = "", data: Any = None) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detail_part = f" | {detail}" if detail else ""
    data_part = ""
    if data is not None:
        try:
            raw = json.dumps(data, ensure_ascii=False, default=str)
            if len(raw) > 2000:
                raw = raw[:2000] + "...(truncated)"
            data_part = f" | {raw}"
        except Exception:
            data_part = " | (serialize error)"
    line = f"[{ts}] [{source}] {action}{detail_part}{data_part}"
    _write(line)


def log_tool_call(source: str, tool: str, args: dict, reason: str = "") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    args_short = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            args_short[k] = v[:200] + "..."
        else:
            args_short[k] = v
    args_json = json.dumps(args_short, ensure_ascii=False, default=str)
    reason_part = f" reason={reason}" if reason else ""
    line = f"[{ts}] [{source}] TOOL_CALL tool={tool} args={args_json}{reason_part}"
    _write(line)


def log_tool_result(source: str, tool: str, success: bool, result_summary: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if success else "FAIL"
    line = f"[{ts}] [{source}] TOOL_RESULT tool={tool} {status} {result_summary}"
    _write(line)


def log_thinking(source: str, mode: str, phase: str, next_action: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{source}] THINKING mode={mode} phase={phase} next={next_action}"
    _write(line)


def log_final(source: str, summary: str, actions: list, decisions: list) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actions_str = "; ".join(str(a) for a in (actions or [])[:5])
    decisions_str = "; ".join(str(d) for d in (decisions or [])[:3])
    line = (
        f"[{ts}] [{source}] FINAL summary={summary[:200]}"
        f" actions=[{actions_str}] decisions=[{decisions_str}]"
    )
    _write(line)
