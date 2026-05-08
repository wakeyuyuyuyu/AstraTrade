from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from runtime.build_context import build_context
from runtime.render_prompt import render_system_prompt
from runtime.agent_loop import run_agent_loop


VALID_MODES = {"scheduler", "manual", "trigger"}


DEFAULT_EXTRA_INSTRUCTIONS = {
    "scheduler": "本轮请优先检查当前市场阶段、持仓、策略和未完成事项，并给出下一步动作建议。",
    "manual": "本轮请优先完成用户给定的自然语言任务。不要默认执行完整自动巡检。",
    "trigger": "本轮请优先处理 trigger_event 相关对象。不要进行无关市场扫描。",
}


def normalize_mode(mode: str | None) -> str:
    if not mode:
        return "scheduler"

    mode = mode.strip().lower()

    if mode not in VALID_MODES:
        return "scheduler"

    return mode


def resolve_mode(mode: str | None, user_task: str = "") -> str:
    """
    Resolve final invocation mode.

    Rule:
    - If user_task exists, mode must be manual.
    - Otherwise, normalize the provided mode.
    """
    if user_task.strip():
        return "manual"

    return normalize_mode(mode)


def default_trigger_reason(mode: str) -> str:
    if mode == "scheduler":
        return "scheduled_run"
    if mode == "manual":
        return "manual_run"
    if mode == "trigger":
        return "trigger_run"
    return "manual_run"


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_text(path: Path, content: str) -> None:
    ensure_parent_dir(path)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_json_object(value: str | None) -> Dict[str, Any]:
    """
    支持两种输入：
    1. JSON 字符串
    2. JSON 文件路径
    """
    if not value:
        return {}

    raw = value.strip()
    if not raw:
        return {}

    path = Path(raw)
    if path.exists() and path.is_file():
        raw = path.read_text(encoding="utf-8").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法 JSON：{e}") from e

    if not isinstance(data, dict):
        raise ValueError("必须是 JSON object")

    return data


def run_once(
    project_root: str | Path,
    mode: str = "scheduler",
    trigger_reason: str | None = None,
    user_task: str = "",
    trigger_event: Dict[str, Any] | None = None,
    extra_instructions: str | None = None,
    max_steps: int = 30,
    max_consecutive_thinking: int = 2,
) -> dict:
    load_dotenv()

    mode = resolve_mode(mode, user_task=user_task)
    trigger_reason = trigger_reason or default_trigger_reason(mode)
    trigger_event = trigger_event or {}

    if extra_instructions is None:
        extra_instructions = DEFAULT_EXTRA_INSTRUCTIONS.get(mode, "")

    root = Path(project_root)
    system_dir = root / "system"
    workspace_dir = root / "workspace"
    skills_dir = workspace_dir / "skills"
    reports_dir = workspace_dir / "reports"
    logs_dir = workspace_dir / "logs"

    now = datetime.now()
    run_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{mode}"

    context = build_context(
        workspace_dir=workspace_dir,
        trigger_reason=trigger_reason,
        now=now,
        mode=mode,
        user_task=user_task,
        trigger_event=trigger_event,
    )

    system_prompt = render_system_prompt(
        system_dir=system_dir,
        workspace_dir=workspace_dir,
        context=context,
        extra_instructions=extra_instructions,
        skills_dir=skills_dir,
        mode=mode,
        user_task=user_task,
        trigger_event=trigger_event,
    )

    prompt_path = reports_dir / f"{run_id}_prompt.md"
    result_path = reports_dir / f"{run_id}_result.json"
    run_log_dir = logs_dir / "agent_runs" / run_id

    save_text(prompt_path, system_prompt)

    result = run_agent_loop(
        system_prompt=system_prompt,
        project_root=root,
        max_steps=max_steps,
        max_consecutive_thinking=max_consecutive_thinking,
        run_log_dir=run_log_dir,
    )

    save_text(result_path, json.dumps(result, ensure_ascii=False, indent=2))

    append_jsonl(
        logs_dir / "agent_runs.jsonl",
        {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "mode": mode,
            "trigger_reason": trigger_reason,
            "user_task": user_task,
            "trigger_event": trigger_event,
            "prompt_file": str(prompt_path.relative_to(root)),
            "result_file": str(result_path.relative_to(root)),
            "run_log_dir": str(run_log_dir.relative_to(root)),
            "success": result.get("success", False),
            "phase": result.get("phase", "unknown"),
            "summary": result.get("summary", ""),
        },
    )

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run stock-agent once.")

    parser.add_argument(
        "--mode",
        default="scheduler",
        choices=["scheduler", "manual", "trigger"],
        help="调用模式：scheduler / manual / trigger。若传入 --task，则会强制改为 manual。",
    )
    parser.add_argument(
        "--trigger-reason",
        default=None,
        help="触发原因，例如 scheduled_run / manual_run / holding_follow_trigger",
    )
    parser.add_argument(
        "--task",
        "--user-task",
        dest="user_task",
        default="",
        help="manual 模式下的自然语言任务。只要该字段非空，mode 必须为 manual。",
    )
    parser.add_argument(
        "--trigger-event",
        default=None,
        help="trigger 模式下的事件 JSON 字符串，或 JSON 文件路径",
    )
    parser.add_argument(
        "--extra-instructions",
        default=None,
        help="本轮附加指令。不传则使用当前 mode 的默认附加指令",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="agent loop 最大步数",
    )
    parser.add_argument(
        "--max-consecutive-thinking",
        type=int,
        default=2,
        help="连续 thinking 最大次数",
    )

    return parser


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]

    parser = build_arg_parser()
    args = parser.parse_args()

    trigger_event = parse_json_object(args.trigger_event)
    mode = resolve_mode(args.mode, user_task=args.user_task)

    result = run_once(
        project_root=project_root,
        mode=mode,
        trigger_reason=args.trigger_reason,
        user_task=args.user_task,
        trigger_event=trigger_event,
        extra_instructions=args.extra_instructions,
        max_steps=args.max_steps,
        max_consecutive_thinking=args.max_consecutive_thinking,
    )

    # print(json.dumps(result, ensure_ascii=False, indent=2))
