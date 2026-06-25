from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from services.llm_service import call_llm
from tools.exec import exec_command
from tools.file_tools import FileTools


# OpenAI 原生 function calling 工具定义。
# 传入 call_llm 的 tools 参数后，DeepSeek API 返回结构化 tool_calls，
# 绕过模型自己拼接 JSON 文本，大幅降低多轮对话中空返回的概率。
AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取 workspace 下的文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于 workspace/ 的文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "写入或覆盖 workspace 下的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于 workspace/ 的文件路径"},
                    "content": {"type": "string", "description": "写入内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "编辑 workspace 下的文件（精确替换）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于 workspace/ 的文件路径"},
                    "oldText": {"type": "string", "description": "被替换的旧文本（精确匹配）"},
                    "newText": {"type": "string", "description": "替换为新文本"},
                },
                "required": ["path", "oldText", "newText"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "在文件末尾追加内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于 workspace/ 的文件路径"},
                    "content": {"type": "string", "description": "追加内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "在项目根目录执行 shell 命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "cwd": {"type": "string", "description": "工作目录（相对于 workspace/，默认 .）"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": "写入记忆文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "记忆类型"},
                    "content": {"type": "string", "description": "记忆内容"},
                },
                "required": ["type", "content"],
            },
        },
    },
]


DEFAULT_FINAL_FIELDS = {
    "mode": "unknown",
    "phase": "unknown",
    "summary": "",
    "actions": [],
    "tool_calls": [],
    "decisions": [],
    "file_updates": [],
    "next_todos": [],
}


OUTPUT_FORMAT_REQUIREMENTS = {
    "thinking": ["type", "mode", "phase", "knowns", "unknowns", "next_action"],
    "tool_call": ["type", "tool", "args", "reason"],
    "final": [
        "type",
        "mode",
        "phase",
        "summary",
        "actions",
        "tool_calls",
        "decisions",
        "file_updates",
        "next_todos",
    ],
}


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


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_agent_run_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def serialize_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "role": m.get("role", ""),
            "content": m.get("content", ""),
        }
        for m in messages
    ]


def normalize_list(value: Any) -> List[Any]:
    """Make final fields stable even when the model returns null/string/object."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_final_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make final output compatible with the new output_contract.md.

    The model may return extra fields, and that is allowed.
    This function only fills required common fields and normalizes list fields.
    """
    normalized = dict(result)

    normalized["type"] = "final"

    for key, default_value in DEFAULT_FINAL_FIELDS.items():
        if key not in normalized:
            normalized[key] = list(default_value) if isinstance(default_value, list) else default_value

    for key in ("actions", "tool_calls", "decisions", "file_updates", "next_todos"):
        normalized[key] = normalize_list(normalized.get(key))

    if not isinstance(normalized.get("summary"), str):
        normalized["summary"] = json.dumps(normalized.get("summary"), ensure_ascii=False)

    if not normalized.get("phase"):
        normalized["phase"] = "unknown"

    if not normalized.get("mode"):
        normalized["mode"] = "unknown"

    return normalized


def assess_model_output_format(parsed: Dict[str, Any]) -> tuple[bool, str]:
    output_type = parsed.get("type")

    if output_type == "error":
        return False, parsed.get("error", "模型输出无法解析为合法 JSON")

    if output_type not in OUTPUT_FORMAT_REQUIREMENTS:
        return False, f"未知 type: {output_type}"

    missing = [key for key in OUTPUT_FORMAT_REQUIREMENTS[output_type] if key not in parsed]
    if missing:
        return False, f"{output_type} 缺少字段: {', '.join(missing)}"

    if output_type == "tool_call" and not isinstance(parsed.get("args"), dict):
        return False, "tool_call.args 必须是 JSON object"

    if output_type == "final":
        list_fields = ["actions", "tool_calls", "decisions", "file_updates", "next_todos"]
        bad_fields = [key for key in list_fields if not isinstance(parsed.get(key), list)]
        if bad_fields:
            return False, f"final 字段必须是数组: {', '.join(bad_fields)}"

    return True, ""


def build_final_result(
    *,
    success: bool,
    summary: str,
    mode: str = "unknown",
    phase: str = "unknown",
    actions: List[Any] | None = None,
    tool_calls: List[Any] | None = None,
    decisions: List[Any] | None = None,
    file_updates: List[Any] | None = None,
    next_todos: List[Any] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": success,
        "type": "final",
        "mode": mode,
        "phase": phase,
        "summary": summary,
        "actions": actions or [],
        "tool_calls": tool_calls or [],
        "decisions": decisions or [],
        "file_updates": file_updates or [],
        "next_todos": next_todos or [],
    }

    if extra:
        result.update(extra)

    return normalize_final_result(result)


def build_parse_error_result(
    *,
    error: str,
    raw_output: str,
) -> Dict[str, Any]:
    """
    Return an explicit protocol error instead of a fake final.

    This lets run_agent_loop retry the model output instead of treating
    parse failures as a completed final result.
    """
    return {
        "type": "error",
        "error_type": "protocol_error",
        "error": error,
        "raw_output": raw_output,
    }


def build_error_retry_message(
    error_reason: str,
    raw_output: str,
    retry_count: int,
    max_retries: int,
) -> str:
    return (
        f"你的上一次输出不符合协议，原因：{error_reason}\n"
        f"这是第 {retry_count}/{max_retries} 次重试。\n\n"
        "请重新输出一个合法 JSON，只能是以下三种之一：\n"
        "1. thinking\n"
        "2. tool_call\n"
        "3. final\n\n"
        "要求：\n"
        "- 必须能被 json.loads() 直接解析，或是单个可提取的 Markdown JSON 代码块\n"
        "- 不要输出多个 JSON 代码块\n"
        "- 不要输出 JSON 之外的文字\n"
        "- thinking 必须包含 type、mode、phase、knowns、unknowns、next_action\n"
        "- tool_call 必须包含 type、tool、args、reason\n"
        "- final 必须包含 type、mode、phase、summary、actions、tool_calls、decisions、file_updates、next_todos\n"
        "- 禁止把工具名写到 type 字段里\n\n"
        f"你的错误输出如下：\n{raw_output}"
    )


def parse_model_output(text: str) -> Dict[str, Any]:
    raw_text = text.strip()

    # 保留 clean_json 的容错能力，但解析失败时返回 error，不再返回 final。
    text = clean_json(raw_text)

    try:
        parsed = json.loads(text)
    except Exception as e:
        return build_parse_error_result(
            error=f"模型输出无法解析为 JSON: {repr(e)}",
            raw_output=raw_text,
        )

    if not isinstance(parsed, dict):
        return build_parse_error_result(
            error="模型输出不是 JSON object",
            raw_output=raw_text,
        )

    return parsed


def execute_tool_call(tool: str, args: Dict[str, Any], project_root: str | Path) -> Dict[str, Any]:
    workspace_root = Path(project_root).resolve() / "workspace"
    file_tools = FileTools(workspace_root)

    if tool == "exec":
        command = args.get("command", "")
        cwd = args.get("cwd", ".")
        return exec_command(command=command, project_root=project_root, cwd=cwd)

    if tool == "write":
        path = args.get("path", "")
        content = args.get("content", "")
        return file_tools.write(path=path, content=content)

    if tool == "edit":
        path = args.get("path", "")
        old_text = args.get("oldText", "")
        new_text = args.get("newText", "")
        return file_tools.edit(path=path, old_text=old_text, new_text=new_text)

    if tool == "read":
        path = args.get("path", "")
        return file_tools.read(path=path)

    if tool == "add":
        path = args.get("path", "")
        content = args.get("content", "")
        return file_tools.add(path=path, content=content)

    if tool == "write_memory":
        memory_type = args.get("type", "")
        content = args.get("content", "")
        return file_tools.write_memory(type=memory_type, content=content)

    return {
        "success": False,
        "error": f"未知工具: {tool}",
    }


def build_continue_message_after_thinking() -> str:
    return (
        "你刚刚已经输出了 thinking。"
        "现在请继续推进任务，只能输出以下三种 JSON 之一：thinking、tool_call、final。"
        "如果需要外部信息，请输出 tool_call；如果已经完成所有任务，请直接输出 final。"
    )


def build_tool_result_message(result: Dict[str, Any]) -> str:
    # print(f"tool result: {result}")
    return (
        "以下是你刚才请求的工具执行结果。"
        "请基于结果继续下一步，只能输出 thinking、tool_call 或 final 三种 JSON。\n\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
    )


def build_forced_stop_result(max_steps: int) -> Dict[str, Any]:
    return build_final_result(
        success=False,
        summary=f"达到最大循环轮数 {max_steps}，已强制结束。",
        actions=["forced_stop"],
        next_todos=["检查是否出现重复 thinking、重复 tool_call 或上下文不足"],
    )


def save_run_summary(
    run_log_path: Path | None,
    final_result: Dict[str, Any],
    steps: int,
    tool_call_history: List[Dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
    agent_trace: List[Dict[str, Any]] | None = None,
    started_at: str | None = None,
) -> None:
    if not run_log_path:
        return

    ended_at = now_str()
    rounded_duration = round(duration_seconds, 3) if duration_seconds is not None else None
    summary = {
        "timestamp": ended_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": rounded_duration,
        "success": final_result.get("success", False),
        "mode": final_result.get("mode", "unknown"),
        "phase": final_result.get("phase", "unknown"),
        "summary": final_result.get("summary", ""),
        "steps": steps,
        "tool_call_count": len(tool_call_history or []),
        "tool_call_history": tool_call_history or [],
        "agent_trace_file": "agent_trace.json" if agent_trace is not None else "",
        "final_result": final_result,
    }

    if agent_trace is not None:
        save_agent_run_json(
            run_log_path / "agent_trace.json",
            {
                "timestamp": ended_at,
                "started_at": started_at,
                "ended_at": ended_at,
                "total_duration_seconds": rounded_duration,
                "steps": len(agent_trace),
                "tool_call_count": len(tool_call_history or []),
                "tool_call_history": tool_call_history or [],
                "final_result": final_result,
                "trace": agent_trace,
            },
        )

    save_agent_run_json(
        run_log_path / "run_summary.json",
        summary,
    )


def run_agent_loop(
    system_prompt: str,
    project_root: str | Path,
    max_steps: int = 10,
    max_consecutive_thinking: int = 2,
    max_error_retries: int = 8,
    run_log_dir: str | Path | None = None,
) -> Dict[str, Any]:
    run_log_path = Path(run_log_dir).resolve() if run_log_dir else None
    run_started_at = now_str()
    run_start = perf_counter()
    step_count = 0
    tool_call_history: List[Dict[str, Any]] = []
    agent_trace: List[Dict[str, Any]] = []

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "开始本轮系统运行。请严格按协议输出 JSON。"},
    ]

    consecutive_thinking = 0
    error_retry_count = 0

    def finalize(result: Dict[str, Any]) -> Dict[str, Any]:
        save_run_summary(
            run_log_path,
            result,
            step_count,
            tool_call_history,
            duration_seconds=perf_counter() - run_start,
            agent_trace=agent_trace,
            started_at=run_started_at,
        )
        return result

    for step_index in range(1, max_steps + 1):
        step_count = step_index
        step_start = perf_counter()
        step_trace: Dict[str, Any] = {
            "step": step_index,
            "started_at": now_str(),
            "input_messages": serialize_messages(messages),
        }
        agent_trace.append(step_trace)

        if run_log_path:
            save_agent_run_json(
                run_log_path / f"step_{step_index:03d}_input.json",
                {
                    "timestamp": now_str(),
                    "step": step_index,
                    "messages": serialize_messages(messages),
                },
            )

        try:
            response_text = call_llm(messages, "main", tools=AGENT_TOOLS)
        except RuntimeError as e:
            response_text = json.dumps({
                "type": "error",
                "error_type": "llm_call_failed",
                "error": str(e),
                "raw_output": "",
            })
        
        parsed = parse_model_output(response_text)
        format_valid, format_error = assess_model_output_format(parsed)
        # print(parsed)
        step_trace.update(
            {
                "ended_at": now_str(),
                "duration_seconds": round(perf_counter() - step_start, 3),
                "raw_output": response_text,
                "parsed_output": parsed,
                "output_type": parsed.get("type"),
                "model_output_format_valid": format_valid,
                "model_output_format_error": format_error,
            }
        )

        if run_log_path:
            save_agent_run_json(
                run_log_path / f"step_{step_index:03d}_output.json",
                {
                    "timestamp": now_str(),
                    "step": step_index,
                    "raw_output": response_text,
                    "parsed_output": parsed,
                },
            )

        if parsed.get("type") == "error":
            error_retry_count += 1

            if error_retry_count > max_error_retries:
                result = build_final_result(
                    success=False,
                    summary=f"模型输出连续 {max_error_retries} 次不符合 JSON 协议，已终止本轮。",
                    next_todos=["检查 prompt 中的循环输出协议", "检查模型输出格式"],
                    extra={
                        "last_error": parsed,
                        "raw_output": parsed.get("raw_output", response_text),
                    },
                )
                return finalize(result)

            messages.append({"role": "assistant", "content": response_text})
            messages.append({
                "role": "user",
                "content": build_error_retry_message(
                    error_reason=parsed.get("error", "输出不符合协议"),
                    raw_output=parsed.get("raw_output", response_text),
                    retry_count=error_retry_count,
                    max_retries=max_error_retries,
                ),
            })
            continue

        output_type = parsed.get("type")

        if output_type == "thinking":
            error_retry_count = 0
            consecutive_thinking += 1
            messages.append({"role": "assistant", "content": response_text})

            if consecutive_thinking > max_consecutive_thinking:
                messages.append({
                    "role": "user",
                    "content": (
                        "你已经连续多次输出 thinking。"
                        "现在必须输出 tool_call 或 final，除非你能明确说明为什么仍然无法行动。"
                    ),
                })
            else:
                messages.append({
                    "role": "user",
                    "content": build_continue_message_after_thinking(),
                })
            continue

        if output_type == "tool_call":
            error_retry_count = 0
            consecutive_thinking = 0

            tool = parsed.get("tool")
            args = parsed.get("args", {})

            if not tool:
                error_retry_count += 1

                if error_retry_count > max_error_retries:
                    result = build_final_result(
                        success=False,
                        summary=f"tool_call 连续 {max_error_retries} 次缺少 tool 字段，已终止本轮。",
                        next_todos=["检查 prompt 中 tool_call 格式要求"],
                        extra={"raw_output": response_text},
                    )
                    return finalize(result)

                messages.append({"role": "assistant", "content": response_text})
                messages.append({
                    "role": "user",
                    "content": build_error_retry_message(
                        error_reason='tool_call 缺少 "tool" 字段。注意 type 必须是 "tool_call"，工具名必须写在 tool 字段中。',
                        raw_output=response_text,
                        retry_count=error_retry_count,
                        max_retries=max_error_retries,
                    ),
                })
                continue

            if not isinstance(args, dict):
                error_retry_count += 1

                if error_retry_count > max_error_retries:
                    result = build_final_result(
                        success=False,
                        summary=f"tool_call 连续 {max_error_retries} 次 args 格式错误，已终止本轮。",
                        next_todos=["检查 prompt 中 args 必须为 JSON object"],
                        extra={"raw_output": response_text},
                    )
                    return finalize(result)

                messages.append({"role": "assistant", "content": response_text})
                messages.append({
                    "role": "user",
                    "content": build_error_retry_message(
                        error_reason='tool_call 的 "args" 必须是 JSON object。',
                        raw_output=response_text,
                        retry_count=error_retry_count,
                        max_retries=max_error_retries,
                    ),
                })
                continue

            tool_result = execute_tool_call(tool, args, project_root)
            step_trace["tool_call"] = {
                "tool": tool,
                "args": args,
                "reason": parsed.get("reason", ""),
                "success": tool_result.get("success"),
                "result": tool_result,
            }
            step_trace["ended_at"] = now_str()
            step_trace["duration_seconds"] = round(perf_counter() - step_start, 3)

            tool_call_record = {
                "step": step_index,
                "timestamp": now_str(),
                "tool": tool,
                "args": args,
                "reason": parsed.get("reason", ""),
                "success": tool_result.get("success"),
                "result": tool_result,
            }
            tool_call_history.append(tool_call_record)

            if run_log_path:
                save_agent_run_json(
                    run_log_path / f"step_{step_index:03d}_tool_result.json",
                    tool_call_record,
                )

            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": build_tool_result_message(tool_result)})
            continue

        if output_type == "final":
            final_result = normalize_final_result(parsed)
            final_result["success"] = True

            # If the model left tool_calls empty, preserve actual tool history.
            if not final_result.get("tool_calls"):
                final_result["tool_calls"] = [
                    {
                        "step": item.get("step"),
                        "tool": item.get("tool"),
                        "args": item.get("args"),
                        "reason": item.get("reason"),
                        "success": item.get("success"),
                    }
                    for item in tool_call_history
                ]

            return finalize(final_result)

        error_retry_count += 1

        if error_retry_count > max_error_retries:
            result = build_final_result(
                success=False,
                summary=f"模型连续 {max_error_retries} 次输出未知 type，已终止本轮。",
                next_todos=["检查循环输出协议"],
                extra={"raw_output": response_text},
            )
            return finalize(result)

        messages.append({"role": "assistant", "content": response_text})
        messages.append({
            "role": "user",
            "content": build_error_retry_message(
                error_reason=f'未知 type: {output_type}。type 只能是 thinking、tool_call、final。',
                raw_output=response_text,
                retry_count=error_retry_count,
                max_retries=max_error_retries,
            ),
        })

    forced = build_forced_stop_result(max_steps)
    return finalize(forced)
