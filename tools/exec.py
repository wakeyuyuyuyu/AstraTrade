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


def ensure_workspace_dir(project_root: Path) -> Path:
    workspace = project_root / "workspace"

    if not workspace.exists() or not workspace.is_dir():
        raise ValueError(f"workspace 目录不存在或不是目录: {workspace}")

    return workspace.resolve()


def resolve_cwd(project_root: Path, cwd: str) -> Path:
    """
    解析 exec 的执行目录。

    统一规则：
    - 默认 cwd="." 表示项目根目录下的 workspace/
    - 相对路径默认相对 workspace/
    - cwd="skills" 表示 workspace/skills/
    - cwd="__project__" 表示项目根目录，仅用于确实需要执行项目级命令时
    - 绝对路径允许，但不能超出项目根目录
    """
    root = project_root.resolve()
    workspace = ensure_workspace_dir(root)

    if not cwd or cwd == ".":
        path = workspace

    elif cwd == "__project__":
        path = root

    else:
        raw = Path(cwd)

        if raw.is_absolute():
            path = raw.resolve()
        else:
            # 兼容模型误传 workspace：cwd="workspace" 仍解析到真实 workspace/
            if raw.parts and raw.parts[0] == "workspace":
                path = (root / raw).resolve()
            else:
                path = (workspace / raw).resolve()

    if not str(path).startswith(str(root)):
        raise ValueError(f"cwd 超出项目根目录: {cwd}")

    if not path.exists() or not path.is_dir():
        raise ValueError(f"cwd 不存在或不是目录: {cwd} -> {path}")

    return path


def _resolve_python(project_root: Path) -> Path | None:
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return None


def exec_command(
    command: str,
    project_root: str | Path,
    cwd: str = ".",
    timeout_seconds: int = 1800,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd_input": cwd,
            "cwd": cwd,
            "cwd_base": "workspace",
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
            "cwd_input": cwd,
            "cwd": cwd,
            "cwd_base": "workspace",
            "stdout": "",
            "stderr": reason,
            "exit_code": -1,
        }

    venv_python = _resolve_python(root)
    if parts and parts[0] in {"python", "python3"} and venv_python:
        parts[0] = str(venv_python)

    try:
        actual_cwd = resolve_cwd(root, cwd)
    except ValueError as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd_input": cwd,
            "cwd": cwd,
            "cwd_base": "workspace",
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
            "cwd_input": cwd,
            "cwd": str(actual_cwd),
            "cwd_base": "project" if actual_cwd == root else "workspace",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd_input": cwd,
            "cwd": str(actual_cwd),
            "cwd_base": "project" if actual_cwd == root else "workspace",
            "stdout": "",
            "stderr": f"命令执行超时（>{timeout_seconds}s）",
            "exit_code": -1,
        }

    except Exception as exc:
        return {
            "success": False,
            "tool": "exec",
            "command": command,
            "cwd_input": cwd,
            "cwd": str(actual_cwd),
            "cwd_base": "project" if actual_cwd == root else "workspace",
            "stdout": "",
            "stderr": f"命令执行异常: {exc}",
            "exit_code": -1,
        }