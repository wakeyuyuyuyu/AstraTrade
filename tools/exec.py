from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List


ALLOWED_BINARIES = {
    "ls",
    "find",
    "cat",
    "sed",
    "head",
    "tail",
    "pwd",
    "python",
    "python3",
    "date",
}

DANGEROUS_TOKENS = {
    "rm",
    "sudo",
    "curl",
    "wget",
    "ssh",
    "scp",
    "mv",
    "chmod",
    "chown",
    "kill",
    "pkill",
    "nohup",
    "screen",
    "tmux",
    ">",
    ">>",
    "|",
    "&&",
    ";",
}


def is_command_allowed(parts: List[str]) -> tuple[bool, str]:
    if not parts:
        return False, "空命令不允许执行"

    for token in parts:
        if token in DANGEROUS_TOKENS:
            return False, f"命令包含禁止 token: {token}"

    binary = parts[0]
    if binary not in ALLOWED_BINARIES:
        return False, f"当前不允许执行该命令: {binary}"

    return True, ""


def resolve_cwd(project_root: Path, cwd: str) -> Path:
    if not cwd:
        return project_root

    path = Path(cwd)
    if not path.is_absolute():
        path = (project_root / cwd).resolve()
    else:
        path = path.resolve()

    if not str(path).startswith(str(project_root.resolve())):
        raise ValueError(f"cwd 超出项目根目录: {cwd}")

    if not path.exists() or not path.is_dir():
        print(cwd)
        raise ValueError(f"cwd 不存在或不是目录: {cwd}")

    return path


def exec_command(
    command: str,
    project_root: str | Path,
    cwd: str = ".",
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd": cwd,
            "stdout": "",
            "stderr": f"命令解析失败: {exc}",
            "exit_code": -1,
        }

    allowed, reason = is_command_allowed(parts)
    if not allowed:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd": cwd,
            "stdout": "",
            "stderr": reason,
            "exit_code": -1,
        }

    try:
        actual_cwd = resolve_cwd(root, cwd)
    except ValueError as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd": cwd,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
        }

    try:
        completed = subprocess.run(
            parts,
            cwd=str(actual_cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "success": completed.returncode == 0,
            "tool": "exec",
            "command": command,
            "cwd": str(actual_cwd),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd": str(actual_cwd),
            "stdout": "",
            "stderr": f"命令执行超时（>{timeout_seconds}s）",
            "exit_code": -1,
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd": str(actual_cwd),
            "stdout": "",
            "stderr": f"命令执行异常: {exc}",
            "exit_code": -1,
        }