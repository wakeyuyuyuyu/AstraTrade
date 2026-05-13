from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.llm_service import call_llm
from runtime.launcher import run_once
from subagent.candidate_follow.candidate_follow import update_candidates


def read_markdown_file(path: Path) -> str:
    if not path.exists():
        return f"# Missing File\n\n文件不存在：{path.name}\n"
    return path.read_text(encoding="utf-8").strip()


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
        return {
            "error_output": text,
        }

    if obj is None:
        return None

    if isinstance(obj, dict):
        return obj

    return {
        "error_output": text,
    }


def is_watchable_candidate(candidate: Dict[str, Any]) -> bool:
    return candidate.get("status") in {"watching", "ready", "trigger_ready", "待观察", "待触发"}


def render_prompts(project_root: str | Path, now_str: str) -> List[Dict[str, Any]]:
    """
    为每个可跟踪 candidate 生成一次盯盘 prompt。

    返回结构：
    [
      {
        "symbol": "...",
        "candidate": {...},
        "prompt": "..."
      }
    ]
    """
    project_root = Path(project_root)

    prompt_path = project_root / "subagent" / "candidate_follow" / "prompt.md"
    candidates_path = project_root / "workspace" / "pools" / "candidates.jsonl"

    base_prompt = read_markdown_file(prompt_path)
    candidates = read_jsonl(candidates_path)

    tasks: List[Dict[str, Any]] = []

    for candidate in candidates:
        if not is_watchable_candidate(candidate):
            continue

        symbol = str(
            candidate.get("symbol")
            or candidate.get("code")
            or candidate.get("stock_code")
            or ""
        ).zfill(6)

        if not symbol:
            continue

        candidate["symbol"] = symbol

        prompt = f"{base_prompt}\n\n"
        prompt += "## 当前时间\n\n"
        prompt += f"{now_str}\n\n"
        prompt += "## 候选股票\n\n"
        prompt += f"```json\n{json.dumps(candidate, ensure_ascii=False, indent=2)}\n```\n"

        tasks.append(
            {
                "symbol": symbol,
                "candidate": candidate,
                "prompt": prompt,
            }
        )

    return tasks


def infer_trigger_type(reason: str) -> str:
    reason_lower = reason.lower()

    if "price_above" in reason_lower:
        return "price_above"
    if "price_below" in reason_lower:
        return "price_below"
    if "breakout" in reason_lower or "突破" in reason:
        return "breakout"
    if "pullback" in reason_lower or "回调" in reason:
        return "pullback"
    if "expired" in reason_lower or "过期" in reason:
        return "candidate_expired"
    if "manual" in reason_lower:
        return "manual_trigger"

    return "candidate_condition"


def build_trigger_event(
    project_root: Path,
    task: Dict[str, Any],
    model_output: Dict[str, Any],
    now_str: str,
) -> Dict[str, Any]:
    candidate = task["candidate"]
    reason = str(model_output.get("reason", ""))

    trigger = candidate.get("trigger") or {}

    return {
        "source": "candidate_follow",
        "trigger_type": infer_trigger_type(reason),
        "symbol": task["symbol"],
        "name": candidate.get("name", ""),
        "candidate_id": model_output.get("candidate_id") or candidate.get("candidate_id") or "",
        "reason": reason,
        "observed": {
            "current_price": candidate.get("current_price"),
            "trigger": trigger,
            "score": candidate.get("score"),
            "status": candidate.get("status"),
        },
        "candidate_snapshot": candidate,
        "timestamp": now_str,
    }


def run_candidate_follow(
    project_root: str | Path,
    update_before_check: bool = True,
    wake_main_agent: bool = True,
    max_steps: int = 30,
) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    if update_before_check:
        update_candidates(now_str)

    tasks = render_prompts(project_root, now_str)
    results: List[Dict[str, Any]] = []

    events_path = project_root / "workspace" / "logs" / "events.jsonl"

    for task in tasks:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": task["prompt"]},
            {"role": "user", "content": "请严格按协议输出 JSON。"},
        ]

        response = call_llm(messages, "sub")
        parsed = parse_model_output(response)

        record: Dict[str, Any] = {
            "timestamp": now_str,
            "source": "candidate_follow",
            "symbol": task["symbol"],
            "candidate_id": task["candidate"].get("candidate_id", ""),
            "triggered": False,
            "model_output": parsed,
        }

        if parsed is None:
            results.append(record)
            continue

        if "error_output" in parsed:
            record["error"] = "model_output_parse_failed"
            results.append(record)
            continue

        candidate_id = parsed.get("candidate_id")
        reason = parsed.get("reason")

        if not candidate_id or not reason:
            record["error"] = "missing_candidate_id_or_reason"
            results.append(record)
            continue

        trigger_event = build_trigger_event(
            project_root=project_root,
            task=task,
            model_output=parsed,
            now_str=now_str,
        )

        record["triggered"] = True
        record["trigger_event"] = trigger_event

        append_jsonl(
            events_path,
            {
                "timestamp": now_str,
                "source": "candidate_follow",
                "event_type": "subagent_trigger",
                "symbol": trigger_event["symbol"],
                "name": trigger_event.get("name", ""),
                "strategy_id": "",
                "candidate_id": trigger_event.get("candidate_id", ""),
                "trigger_type": trigger_event.get("trigger_type", ""),
                "reason": trigger_event.get("reason", ""),
                "trigger_event": trigger_event,
            },
        )

        if wake_main_agent:
            main_result = run_once(
                project_root=project_root,
                mode="trigger",
                trigger_reason="candidate_follow_trigger",
                trigger_event=trigger_event,
                extra_instructions="本轮由 candidate_follow 子 Agent 触发。请只处理 trigger_event 相关候选股票，先核验触发条件，再决定是否升级为策略、买入或记录观察。",
                max_steps=max_steps,
            )
            record["main_agent_result"] = main_result

        results.append(record)

    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run candidate follow subagent.")

    parser.add_argument(
        "--no-update",
        action="store_true",
        help="不先同步候选池行情，直接使用 workspace/pools/candidates.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只判断是否触发，不唤醒主 Agent",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=30,
        help="唤醒主 Agent 后的最大执行步数",
    )

    return parser


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    args = build_arg_parser().parse_args()

    results = run_candidate_follow(
        project_root=project_root,
        update_before_check=not args.no_update,
        wake_main_agent=not args.dry_run,
        max_steps=args.max_steps,
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
