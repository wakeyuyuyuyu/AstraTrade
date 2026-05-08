from __future__ import annotations

import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.investment_style import (  # noqa: E402
    DEFAULT_STYLE_CONFIG,
    STYLE_LIBRARY,
    STYLE_RULES,
    TITLE_MAP,
    InvestmentStyle,
    write_style_md,
)


DASHBOARD_DIR = ROOT / "dashboard"
STATIC_DIR = DASHBOARD_DIR / "static"
RUNTIME_DIR = DASHBOARD_DIR / "runtime"
WORKSPACE_DIR = ROOT / "workspace"
CONFIG_DIR = ROOT / "config"

STYLE_CONFIG_PATH = CONFIG_DIR / "investment_style.json"
STYLE_MD_PATH = WORKSPACE_DIR / "STYLE.md"
MANUAL_RUNS_PATH = RUNTIME_DIR / "manual_runs.jsonl"
INITIALIZATION_RUNS_PATH = RUNTIME_DIR / "initialization_runs.jsonl"
SCHEDULER_PID_PATH = RUNTIME_DIR / "scheduler.pid.json"
SCHEDULER_LOG_PATH = RUNTIME_DIR / "scheduler.log"
INITIALIZATION_LOG_PATH = RUNTIME_DIR / "initialization.log"
SCHEDULER_CONFIG_PATH = CONFIG_DIR / "scheduler.json"
SCHEDULER_SOURCE_PATH = ROOT / "runtime" / "scheduler.py"
INITIALIZATION_SCRIPT_PATH = ROOT / "initialization.sh"
ENV_PATH = ROOT / ".env"
DEFAULT_AGENT_ENV_NAME = "stagent"


def resolve_agent_python() -> str:
    configured = (
        os.environ.get("STOCK_AGENT_PYTHON")
        or os.environ.get("DASHBOARD_AGENT_PYTHON")
        or ""
    ).strip()
    candidates = []

    if configured:
        candidates.append(Path(configured))

    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if os.environ.get("CONDA_DEFAULT_ENV") == DEFAULT_AGENT_ENV_NAME and conda_prefix:
        candidates.append(Path(conda_prefix) / "bin" / "python")

    candidates.extend(
        [
            Path("/opt/miniconda3/envs") / DEFAULT_AGENT_ENV_NAME / "bin" / "python",
            Path("/opt/anaconda3/envs") / DEFAULT_AGENT_ENV_NAME / "bin" / "python",
            Path.home() / "miniconda3" / "envs" / DEFAULT_AGENT_ENV_NAME / "bin" / "python",
            Path.home() / "anaconda3" / "envs" / DEFAULT_AGENT_ENV_NAME / "bin" / "python",
            ROOT / ".venv" / "bin" / "python",
            Path(sys.executable),
        ]
    )

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return sys.executable


AGENT_PYTHON = resolve_agent_python()


def agent_subprocess_env() -> Dict[str, str]:
    env = os.environ.copy()
    python_path = Path(AGENT_PYTHON)
    python_bin = str(python_path.parent)
    env["PATH"] = f"{python_bin}:{env.get('PATH', '')}"

    if python_path.parent.parent.name == DEFAULT_AGENT_ENV_NAME:
        env["CONDA_DEFAULT_ENV"] = DEFAULT_AGENT_ENV_NAME
        env["CONDA_PREFIX"] = str(python_path.parent.parent)

    return env

API_ENV_VARS = [
    {
        "key": "LLM_API_KEY",
        "label": "LLM API Key",
        "description": "OpenAI 兼容接口密钥，用于主 Agent 调用模型。",
        "secret": True,
    },
    {
        "key": "LLM_MODEL",
        "label": "LLM Model",
        "description": "模型名称，例如 qwen、deepseek、gpt 兼容模型名。",
        "secret": False,
    },
    {
        "key": "LLM_URL",
        "label": "LLM Base URL",
        "description": "OpenAI 兼容 Chat Completions 服务地址，通常以 /v1 结尾。",
        "secret": False,
    },
    {
        "key": "MX_APIKEY",
        "label": "妙想 API Key",
        "description": "东方财富妙想 Skills API Key，用于行情、资讯和模拟组合。",
        "secret": True,
    },
    {
        "key": "MX_API_URL",
        "label": "妙想 API URL",
        "description": "妙想模拟交易 API 基础地址。",
        "secret": False,
    },
]


class DashboardState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active_process: subprocess.Popen[str] | None = None
        self.active_run: Dict[str, Any] | None = None
        self.recent_manual_runs: List[Dict[str, Any]] = []
        self.scheduler_process: subprocess.Popen[str] | None = None
        self.initialization_process: subprocess.Popen[str] | None = None
        self.active_initialization: Dict[str, Any] | None = None
        self.recent_initializations: List[Dict[str, Any]] = []


STATE = DashboardState()


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def read_json(path: Path, default: Any) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": str(exc), "_path": str(path.relative_to(ROOT))}


def read_jsonl(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    items: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                items.append(obj)
    except Exception:
        return []

    if limit is not None:
        return items[-limit:]
    return items


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail_text(path: Path, lines: int = 24) -> List[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []


LOG_TS_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
SCHEDULER_RUN_RE = re.compile(r"^RUN task=([^\s]+)\s+command=(.*)$")
SCHEDULER_EXIT_RE = re.compile(r"^EXIT_CODE task=([^\s]+)\s+code=(-?\d+)")


def scheduler_log_paths() -> List[Path]:
    today_log = WORKSPACE_DIR / "logs" / "scheduler" / f"{time.strftime('%Y-%m-%d')}.log"
    return [today_log, SCHEDULER_LOG_PATH]


def parse_scheduler_calls(paths: List[Path], limit: int = 8) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for path in paths:
        for line in tail_text(path, lines=5000):
            ts_match = LOG_TS_RE.match(line)
            if not ts_match:
                continue

            timestamp, message = ts_match.groups()
            run_match = SCHEDULER_RUN_RE.match(message)
            if run_match:
                task, command = run_match.groups()
                key = (timestamp, task, command)
                if key in seen:
                    continue
                seen.add(key)
                calls.append(
                    {
                        "time": timestamp,
                        "task": task,
                        "command": command,
                        "source": rel(path),
                    }
                )
                continue

            exit_match = SCHEDULER_EXIT_RE.match(message)
            if exit_match:
                task, code = exit_match.groups()
                for call in reversed(calls):
                    if call.get("task") == task and "exit_code" not in call:
                        call["exit_code"] = int(code)
                        call["ended_at"] = timestamp
                        break

    calls.sort(key=lambda item: item.get("time", ""), reverse=True)
    return calls[:limit]


def scheduler_log_payload(lines: int = 18) -> Dict[str, Any]:
    candidates = scheduler_log_paths()
    for path in candidates:
        tail = tail_text(path, lines=lines)
        if tail:
            return {
                "file": rel(path),
                "tail": tail,
                "sources": [rel(item) for item in candidates],
                "calls": parse_scheduler_calls(candidates),
            }

    return {
        "file": rel(candidates[0]),
        "tail": [],
        "sources": [rel(item) for item in candidates],
        "calls": [],
    }


def pid_is_running(pid: int | None) -> bool:
    if not pid:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def read_scheduler_record() -> Dict[str, Any]:
    if not SCHEDULER_PID_PATH.exists():
        return {}

    data = read_json(SCHEDULER_PID_PATH, {})
    return data if isinstance(data, dict) else {}


def write_scheduler_record(record: Dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULER_PID_PATH.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_scheduler_record() -> None:
    try:
        SCHEDULER_PID_PATH.unlink()
    except FileNotFoundError:
        pass


def file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def scheduler_signature() -> Dict[str, float]:
    return {
        "scheduler_mtime": file_mtime(SCHEDULER_SOURCE_PATH),
        "config_mtime": file_mtime(SCHEDULER_CONFIG_PATH),
    }


def scheduler_record_is_stale(record: Dict[str, Any]) -> bool:
    expected = scheduler_signature()
    for key, value in expected.items():
        if float(record.get(key) or 0) != value:
            return True
    return False


def validate_time_value(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field_name} 必须是 HH:MM 格式")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是 HH:MM 格式") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"{field_name} 时间超出范围")

    return f"{hour:02d}:{minute:02d}"


def clean_command_value(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{field_name} 不能包含换行")
    return text


def default_scheduler_config() -> Dict[str, Any]:
    return {
        "timezone": "Asia/Shanghai",
        "main_agent_command": "python -m runtime.launcher",
        "check_interval_seconds": 30,
        "run_on_weekdays_only": True,
        "fixed_jobs": [],
        "market_sessions": [],
        "market_subagents": [],
    }


def scheduler_config_payload() -> Dict[str, Any]:
    config = read_json(SCHEDULER_CONFIG_PATH, default_scheduler_config())
    if not isinstance(config, dict):
        config = default_scheduler_config()

    fixed_jobs = config.get("fixed_jobs") if isinstance(config.get("fixed_jobs"), list) else []
    market_sessions = config.get("market_sessions") if isinstance(config.get("market_sessions"), list) else []
    market_subagents = config.get("market_subagents") if isinstance(config.get("market_subagents"), list) else []

    return {
        "file": rel(SCHEDULER_CONFIG_PATH),
        "mtime": file_mtime(SCHEDULER_CONFIG_PATH),
        "config": config,
        "summary": {
            "fixed_enabled": sum(1 for item in fixed_jobs if isinstance(item, dict) and item.get("enabled", True)),
            "fixed_total": len(fixed_jobs),
            "session_count": len(market_sessions),
            "subagent_enabled": sum(1 for item in market_subagents if isinstance(item, dict) and item.get("enabled", True)),
            "subagent_total": len(market_subagents),
        },
    }


def normalize_scheduler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "timezone": str(config.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai",
        "main_agent_command": clean_command_value(config.get("main_agent_command", "python -m runtime.launcher"), "主 Agent 命令"),
        "run_on_weekdays_only": bool(config.get("run_on_weekdays_only", True)),
    }

    try:
        interval = int(config.get("check_interval_seconds", 30))
    except Exception as exc:
        raise ValueError("检查间隔必须是数字") from exc
    if interval < 5 or interval > 3600:
        raise ValueError("检查间隔必须在 5 到 3600 秒之间")
    normalized["check_interval_seconds"] = interval

    fixed_jobs = []
    for index, item in enumerate(config.get("fixed_jobs") or [], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"固定任务 #{index} 必须是对象")
        fixed_jobs.append(
            {
                "name": clean_command_value(item.get("name"), f"固定任务 #{index} 名称"),
                "enabled": bool(item.get("enabled", True)),
                "time": validate_time_value(item.get("time"), f"固定任务 #{index} 时间"),
                "trigger_reason": clean_command_value(item.get("trigger_reason"), f"固定任务 #{index} 触发原因"),
            }
        )
    normalized["fixed_jobs"] = fixed_jobs

    sessions = []
    for index, item in enumerate(config.get("market_sessions") or [], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"交易时段 #{index} 必须是对象")
        try:
            minutes = int(item.get("interval_minutes", 10))
        except Exception as exc:
            raise ValueError(f"交易时段 #{index} 间隔必须是数字") from exc
        if minutes < 1 or minutes > 240:
            raise ValueError(f"交易时段 #{index} 间隔必须在 1 到 240 分钟之间")
        start = validate_time_value(item.get("start"), f"交易时段 #{index} 开始时间")
        end = validate_time_value(item.get("end"), f"交易时段 #{index} 结束时间")
        if start >= end:
            raise ValueError(f"交易时段 #{index} 的结束时间必须晚于开始时间")
        sessions.append({"start": start, "end": end, "interval_minutes": minutes})
    normalized["market_sessions"] = sessions

    subagents = []
    for index, item in enumerate(config.get("market_subagents") or [], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"子 Agent #{index} 必须是对象")
        subagents.append(
            {
                "name": clean_command_value(item.get("name"), f"子 Agent #{index} 名称"),
                "enabled": bool(item.get("enabled", True)),
                "command": clean_command_value(item.get("command"), f"子 Agent #{index} 命令"),
            }
        )
    normalized["market_subagents"] = subagents

    return normalized


def validate_no_new_subagents(config: Dict[str, Any]) -> None:
    current = scheduler_config_payload().get("config", {})
    current_items = current.get("market_subagents") if isinstance(current, dict) else []
    current_names = {
        str(item.get("name") or "").strip()
        for item in (current_items or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }

    incoming_items = config.get("market_subagents") or []
    if not isinstance(incoming_items, list):
        raise ValueError("子 Agent 配置必须是数组")

    incoming_names = {
        str(item.get("name") or "").strip()
        for item in incoming_items
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }

    unknown = sorted(incoming_names - current_names)
    if unknown:
        raise ValueError(f"当前系统不支持新增子 Agent: {', '.join(unknown)}")


def save_scheduler_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = payload.get("config", payload)
    if not isinstance(config, dict):
        raise ValueError("Scheduler 配置必须是 JSON object")

    validate_no_new_subagents(config)
    normalized = normalize_scheduler_config(config)
    was_running = bool(scheduler_status().get("running"))

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULER_CONFIG_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    restarted = False
    if was_running:
        stop_scheduler()
        start_scheduler(auto=True)
        restarted = True

    return {
        "success": True,
        "message": "Scheduler 配置已保存" + ("，已重启 scheduler" if restarted else ""),
        "restarted": restarted,
        "config": scheduler_config_payload(),
        "scheduler": scheduler_status(),
    }


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def normalize_style_config(config: Dict[str, Any]) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}

    for dimension in STYLE_LIBRARY:
        value = config.get(dimension, DEFAULT_STYLE_CONFIG.get(dimension, []))

        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = [str(item) for item in value]
        else:
            values = []

        allowed = set(STYLE_LIBRARY[dimension])
        selected = [item for item in values if item in allowed]

        if not selected:
            selected = list(DEFAULT_STYLE_CONFIG.get(dimension, []))

        normalized[dimension] = selected

    return normalized


def load_style_config() -> Dict[str, List[str]]:
    raw = read_json(STYLE_CONFIG_PATH, DEFAULT_STYLE_CONFIG)
    if not isinstance(raw, dict):
        raw = DEFAULT_STYLE_CONFIG
    return normalize_style_config(raw)


def style_payload() -> Dict[str, Any]:
    return {
        "config": load_style_config(),
        "options": {
            dimension: [
                {"key": key, "description": description}
                for key, description in options.items()
            ]
            for dimension, options in STYLE_LIBRARY.items()
        },
        "rules": STYLE_RULES,
        "titles": TITLE_MAP,
        "files": {
            "config": rel(STYLE_CONFIG_PATH),
            "style_md": rel(STYLE_MD_PATH),
        },
    }


def parse_env_assignment(line: str) -> tuple[str | None, str | None]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None, None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key.removeprefix("export ").strip()

    if not key:
        return None, None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return key, value


def read_env_values() -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return values

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        key, value = parse_env_assignment(line)
        if key and value is not None:
            values[key] = value

    return values


def mask_env_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def api_config_payload() -> Dict[str, Any]:
    values = read_env_values()
    variables = []

    for item in API_ENV_VARS:
        key = item["key"]
        value = values.get(key, "")
        variables.append(
            {
                **item,
                "configured": bool(value),
                "masked_value": mask_env_value(value) if item.get("secret") else value,
            }
        )

    return {
        "env_file": rel(ENV_PATH),
        "variables": variables,
    }


def scheduler_status() -> Dict[str, Any]:
    with STATE.lock:
        process = STATE.scheduler_process

    log_payload = scheduler_log_payload(lines=18)
    expected_signature = scheduler_signature()
    record = read_scheduler_record()
    pid = int(record.get("pid") or 0)

    if process is not None and process.poll() is None:
        pid = process.pid
        if not record:
            record = {
                "pid": pid,
                "started_at": "",
                "command": f"{AGENT_PYTHON} -m runtime.scheduler",
                "source": "dashboard",
                **expected_signature,
            }

    running = pid_is_running(pid)
    restart_required = bool(record and running and scheduler_record_is_stale(record))
    if record and not running:
        clear_scheduler_record()

    return {
        "running": running,
        "pid": pid if running else None,
        "started_at": record.get("started_at", "") if running else "",
        "command": record.get("command", f"{AGENT_PYTHON} -m runtime.scheduler"),
        "python": AGENT_PYTHON,
        "source": record.get("source", "dashboard"),
        "config_file": rel(SCHEDULER_CONFIG_PATH),
        "log_file": log_payload["file"],
        "log_sources": log_payload["sources"],
        "log_tail": log_payload["tail"],
        "log_calls": log_payload["calls"],
        "scheduler_mtime": record.get("scheduler_mtime") or 0,
        "config_mtime": record.get("config_mtime") or 0,
        "expected_scheduler_mtime": expected_signature["scheduler_mtime"],
        "expected_config_mtime": expected_signature["config_mtime"],
        "restart_required": restart_required,
    }


def start_scheduler(auto: bool = False) -> Dict[str, Any]:
    with STATE.lock:
        existing = STATE.scheduler_process
        existing_running = existing is not None and existing.poll() is None

    if existing_running:
        return {
            "success": True,
            "message": "scheduler 已在运行",
            "scheduler": scheduler_status(),
        }

    status = scheduler_status()
    if status["running"]:
        expected_command = f"{AGENT_PYTHON} -m runtime.scheduler"
        if status.get("command") != expected_command or status.get("restart_required"):
            stop_scheduler()
            status = scheduler_status()
        else:
            return {
                "success": True,
                "message": "scheduler 已在运行",
                "scheduler": status,
            }

    if status["running"]:
        return {
            "success": True,
            "message": "scheduler 已在运行",
            "scheduler": status,
        }

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    command = [AGENT_PYTHON, "-m", "runtime.scheduler"]
    command_label = " ".join(command)

    with SCHEDULER_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{now_str()}] dashboard starting scheduler auto={auto}\n")
        log_file.flush()
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=agent_subprocess_env(),
            start_new_session=True,
        )

    record = {
        "pid": process.pid,
        "started_at": now_str(),
        "command": command_label,
        "source": "dashboard_auto_start" if auto else "dashboard_button",
        **scheduler_signature(),
    }
    write_scheduler_record(record)

    with STATE.lock:
        STATE.scheduler_process = process

    return {
        "success": True,
        "message": "scheduler 已启动",
        "scheduler": scheduler_status(),
    }


def stop_scheduler() -> Dict[str, Any]:
    status = scheduler_status()
    pid = status.get("pid")

    if not pid:
        clear_scheduler_record()
        return {
            "success": True,
            "message": "scheduler 未运行",
            "scheduler": scheduler_status(),
        }

    with STATE.lock:
        process = STATE.scheduler_process

    try:
        if process is not None and process.pid == pid and process.poll() is None:
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except Exception:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                except Exception:
                    process.kill()
                process.wait(timeout=5)
        else:
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except Exception:
                os.kill(int(pid), signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline and pid_is_running(int(pid)):
                time.sleep(0.2)
            if pid_is_running(int(pid)):
                try:
                    os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                except Exception:
                    os.kill(int(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass

    clear_scheduler_record()

    with SCHEDULER_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{now_str()}] dashboard stopped scheduler pid={pid}\n")

    return {
        "success": True,
        "message": "scheduler 已停止",
        "scheduler": scheduler_status(),
    }


def format_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(ch in value for ch in [" ", "\t", "#", '"', "'", "\\"]):
        return json.dumps(value, ensure_ascii=False)
    return value


def save_api_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    env_updates = payload.get("env", payload)
    if not isinstance(env_updates, dict):
        raise ValueError("API 配置必须是 JSON object")

    allowed_keys = {item["key"] for item in API_ENV_VARS}
    updates: Dict[str, str] = {}

    for key, value in env_updates.items():
        key = str(key).strip()
        if key not in allowed_keys:
            raise ValueError(f"不支持的环境变量: {key}")

        if value is None:
            continue

        value = str(value)
        if value == "":
            continue

        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} 不能包含换行")

        updates[key] = value

    if not updates:
        return {
            "success": True,
            "updated": [],
            "config": api_config_payload(),
        }

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    updated_lines: List[str] = []

    for line in lines:
        key, _ = parse_env_assignment(line)
        if key in updates:
            updated_lines.append(f"{key}={format_env_value(updates[key])}")
            seen.add(key)
        else:
            updated_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            updated_lines.append(f"{key}={format_env_value(value)}")

    ENV_PATH.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

    return {
        "success": True,
        "updated": sorted(updates.keys()),
        "config": api_config_payload(),
    }


def summarize_number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def pool_metrics(holdings: List[Dict[str, Any]], strategies: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    active_strategy_status = {"active", "pending", "watching", "trigger_ready", "待执行", "执行中"}
    candidate_status = {"watching", "ready", "trigger_ready", "待观察", "待触发"}

    return {
        "holdings_count": len(holdings),
        "holdings_market_value": sum(summarize_number(item.get("market_value")) for item in holdings),
        "strategies_count": len(strategies),
        "active_strategies_count": sum(1 for item in strategies if item.get("status") in active_strategy_status),
        "candidates_count": len(candidates),
        "watching_candidates_count": sum(1 for item in candidates if item.get("status") in candidate_status),
    }


def list_run_dirs(limit: int = 12) -> List[Path]:
    runs_dir = WORKSPACE_DIR / "logs" / "agent_runs"
    if not runs_dir.exists():
        return []

    dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return dirs[:limit]


def read_run_summary(run_dir: Path) -> Dict[str, Any]:
    summary_path = run_dir / "run_summary.json"
    summary = read_json(summary_path, {})
    if not isinstance(summary, dict):
        summary = {}

    return {
        "run_id": run_dir.name,
        "path": rel(run_dir),
        "summary": summary.get("summary") or summary.get("final_result", {}).get("summary", ""),
        "success": summary.get("success"),
        "mode": summary.get("mode") or summary.get("final_result", {}).get("mode", ""),
        "phase": summary.get("phase") or summary.get("final_result", {}).get("phase", ""),
        "steps": summary.get("steps", 0),
        "tool_call_count": summary.get("tool_call_count", 0),
        "timestamp": summary.get("timestamp", ""),
    }


def compact_json(value: Any, limit: int = 900) -> str:
    if value in (None, "", [], {}):
        return ""

    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2)

    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def parsed_step_text(parsed: Dict[str, Any], raw: str) -> str:
    output_type = parsed.get("type", "")

    if output_type == "thinking":
        chunks = [
            compact_json(parsed.get("knowns"), 300),
            compact_json(parsed.get("unknowns"), 300),
            str(parsed.get("next_action") or ""),
        ]
        return "\n".join(chunk for chunk in chunks if chunk) or raw[:800]

    if output_type == "tool_call":
        return str(parsed.get("reason") or "") or raw[:800]

    if output_type == "final":
        chunks = [
            str(parsed.get("summary") or ""),
            compact_json(parsed.get("actions"), 500),
            compact_json(parsed.get("decisions"), 500),
            compact_json(parsed.get("next_todos"), 500),
        ]
        return "\n".join(chunk for chunk in chunks if chunk) or raw[:800]

    if output_type == "error":
        return str(parsed.get("error") or parsed.get("error_type") or raw[:800])

    return str(parsed.get("summary") or parsed.get("next_action") or parsed.get("reason") or raw[:800])


def tool_result_text(tool_data: Dict[str, Any]) -> str:
    result = tool_data.get("result") or {}
    if not isinstance(result, dict):
        return compact_json(result, 900)

    chunks = [
        str(result.get("error") or ""),
        str(result.get("path") or ""),
        str(result.get("stdout") or "")[:800],
        str(result.get("stderr") or "")[:500],
        compact_json(result.get("content"), 900),
    ]
    return "\n".join(chunk for chunk in chunks if chunk) or compact_json(result, 900)


def read_run_trace(run_dir: Path) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    output_files = sorted(run_dir.glob("step_*_output.json"))
    for output_file in output_files:
        data = read_json(output_file, {})
        parsed = data.get("parsed_output", {}) if isinstance(data, dict) else {}
        raw = data.get("raw_output", "") if isinstance(data, dict) else ""
        step = data.get("step") if isinstance(data, dict) else None
        parsed = parsed if isinstance(parsed, dict) else {}

        item = {
            "kind": "model",
            "step": step,
            "timestamp": data.get("timestamp", "") if isinstance(data, dict) else "",
            "type": parsed.get("type", "") if isinstance(parsed, dict) else "",
            "tool": parsed.get("tool", "") if isinstance(parsed, dict) else "",
            "reason": parsed.get("reason", "") if isinstance(parsed, dict) else "",
            "summary": parsed.get("summary", "") if isinstance(parsed, dict) else "",
            "next_action": parsed.get("next_action", "") if isinstance(parsed, dict) else "",
            "args": parsed.get("args", {}) if isinstance(parsed, dict) else {},
            "actions": parsed.get("actions", []) if isinstance(parsed, dict) else [],
            "decisions": parsed.get("decisions", []) if isinstance(parsed, dict) else [],
            "next_todos": parsed.get("next_todos", []) if isinstance(parsed, dict) else [],
            "tool_calls": parsed.get("tool_calls", []) if isinstance(parsed, dict) else [],
            "body": parsed_step_text(parsed, raw),
            "raw_preview": raw[:800],
        }
        steps.append(item)

        tool_file = run_dir / output_file.name.replace("_output.json", "_tool_result.json")
        if tool_file.exists():
            tool_data = read_json(tool_file, {})
            if isinstance(tool_data, dict):
                result = tool_data.get("result") or {}
                steps.append(
                    {
                        "kind": "tool",
                        "step": tool_data.get("step"),
                        "timestamp": tool_data.get("timestamp", ""),
                        "tool": tool_data.get("tool", ""),
                        "reason": tool_data.get("reason", ""),
                        "success": tool_data.get("success"),
                        "exit_code": result.get("exit_code") if isinstance(result, dict) else None,
                        "path": result.get("path", "") if isinstance(result, dict) else "",
                        "error": result.get("error", "") if isinstance(result, dict) else "",
                        "body": tool_result_text(tool_data),
                    }
                )

    if not steps:
        summary = read_json(run_dir / "run_summary.json", {})
        if isinstance(summary, dict):
            for item in summary.get("tool_call_history", []) or []:
                if isinstance(item, dict):
                    steps.append(
                        {
                            "kind": "tool",
                            "step": item.get("step"),
                            "timestamp": item.get("timestamp", ""),
                            "tool": item.get("tool", ""),
                            "reason": item.get("reason", ""),
                            "success": item.get("success"),
                            "args": item.get("args", {}),
                            "body": tool_result_text(item),
                        }
                    )

    return {
        "run": read_run_summary(run_dir),
        "steps": steps,
    }


def read_trace_by_run_id(run_id: str) -> Dict[str, Any]:
    run_id = run_id.strip()
    if not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("无效的 run_id")

    runs_dir = WORKSPACE_DIR / "logs" / "agent_runs"
    run_dir = (runs_dir / run_id).resolve()

    if not str(run_dir).startswith(str(runs_dir.resolve())) or not run_dir.is_dir():
        raise ValueError(f"找不到调用轨迹: {run_id}")

    return read_run_trace(run_dir)


def manual_run_status() -> Dict[str, Any]:
    with STATE.lock:
        process = STATE.active_process
        active = STATE.active_run
        recent = list(STATE.recent_manual_runs)

    is_running = process is not None and process.poll() is None
    return {
        "running": is_running,
        "active": active if is_running else None,
        "recent": recent[-10:],
    }


def initialization_status() -> Dict[str, Any]:
    with STATE.lock:
        process = STATE.initialization_process
        active = STATE.active_initialization
        recent = list(STATE.recent_initializations)

    is_running = process is not None and process.poll() is None
    return {
        "running": is_running,
        "active": active if is_running else None,
        "recent": recent[-8:],
        "script": rel(INITIALIZATION_SCRIPT_PATH),
        "log_file": rel(INITIALIZATION_LOG_PATH),
        "log_tail": tail_text(INITIALIZATION_LOG_PATH, lines=18),
    }


def start_initialization() -> Dict[str, Any]:
    if not INITIALIZATION_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"找不到初始化脚本: {rel(INITIALIZATION_SCRIPT_PATH)}")

    with STATE.lock:
        init_process = STATE.initialization_process
        manual_process = STATE.active_process
        if init_process is not None and init_process.poll() is None:
            raise RuntimeError("初始化正在运行，请等待完成")
        if manual_process is not None and manual_process.poll() is None:
            raise RuntimeError("人工指令正在运行，请等待完成后再初始化")

    scheduler_was_running = bool(scheduler_status().get("running"))
    if scheduler_was_running:
        stop_scheduler()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "id": f"init_{int(time.time())}",
        "started_at": now_str(),
        "status": "running",
        "script": rel(INITIALIZATION_SCRIPT_PATH),
        "stopped_scheduler": scheduler_was_running,
    }

    with INITIALIZATION_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{now_str()}] dashboard starting initialization\n")
        log_file.flush()
        process = subprocess.Popen(
            ["/bin/bash", str(INITIALIZATION_SCRIPT_PATH)],
            cwd=str(ROOT),
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    with STATE.lock:
        STATE.initialization_process = process
        STATE.active_initialization = record

    def finish() -> None:
        return_code = process.wait()
        final = dict(record)
        final.update(
            {
                "ended_at": now_str(),
                "status": "success" if return_code == 0 else "failed",
                "exit_code": return_code,
                "restarted_scheduler": False,
            }
        )

        if scheduler_was_running:
            try:
                start_scheduler(auto=True)
                final["restarted_scheduler"] = True
            except Exception as exc:
                final["restart_error"] = str(exc)

        append_jsonl(INITIALIZATION_RUNS_PATH, final)

        with STATE.lock:
            STATE.recent_initializations.append(final)
            STATE.recent_initializations = STATE.recent_initializations[-20:]
            if STATE.initialization_process is process:
                STATE.initialization_process = None
                STATE.active_initialization = None

    threading.Thread(target=finish, daemon=True).start()
    return {
        "success": True,
        "message": "初始化已启动",
        "initialization": initialization_status(),
        "scheduler": scheduler_status(),
    }


def build_snapshot() -> Dict[str, Any]:
    account = read_json(WORKSPACE_DIR / "state" / "account_state.json", {})
    market = read_json(WORKSPACE_DIR / "state" / "market_state.json", {})
    holdings = read_jsonl(WORKSPACE_DIR / "pools" / "holdings.jsonl")
    strategies = read_jsonl(WORKSPACE_DIR / "pools" / "strategies.jsonl")
    candidates = read_jsonl(WORKSPACE_DIR / "pools" / "candidates.jsonl")

    return {
        "updated_at": now_str(),
        "account": account,
        "market": market,
        "holdings": holdings,
        "stock_pool": strategies,
        "candidates": candidates,
        "metrics": pool_metrics(holdings, strategies, candidates),
        "style": style_payload(),
        "api_config": api_config_payload(),
        "scheduler_config": scheduler_config_payload(),
        "logs": {
            "agent_runs": list(reversed(read_jsonl(WORKSPACE_DIR / "logs" / "agent_runs.jsonl", limit=25))),
            "decisions": list(reversed(read_jsonl(WORKSPACE_DIR / "logs" / "decisions.jsonl", limit=12))),
            "trades": list(reversed(read_jsonl(WORKSPACE_DIR / "logs" / "trades.jsonl", limit=12))),
            "events": list(reversed(read_jsonl(WORKSPACE_DIR / "logs" / "events.jsonl", limit=12))),
            "run_dirs": [read_run_summary(path) for path in list_run_dirs(limit=12)],
        },
        "manual_run": manual_run_status(),
        "scheduler": scheduler_status(),
        "initialization": initialization_status(),
    }


def start_manual_run(task: str, max_steps: int = 50) -> Dict[str, Any]:
    task = task.strip()
    if not task:
        raise ValueError("人工指令不能为空")

    max_steps = max(1, min(int(max_steps), 100))

    with STATE.lock:
        if STATE.active_process is not None and STATE.active_process.poll() is None:
            raise RuntimeError("已有人工指令正在运行，请等待本轮结束")

        record = {
            "id": f"manual_{int(time.time())}",
            "task": task,
            "started_at": now_str(),
            "status": "running",
            "max_steps": max_steps,
        }

        process = subprocess.Popen(
            [
                AGENT_PYTHON,
                "-m",
                "runtime.launcher",
                "--task",
                task,
                "--max-steps",
                str(max_steps),
            ],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=agent_subprocess_env(),
        )

        STATE.active_process = process
        STATE.active_run = record

    def finish() -> None:
        stdout, stderr = process.communicate()
        ended = now_str()
        final = dict(record)
        final.update(
            {
                "ended_at": ended,
                "status": "success" if process.returncode == 0 else "failed",
                "exit_code": process.returncode,
                "stdout_preview": (stdout or "")[-3000:],
                "stderr_preview": (stderr or "")[-3000:],
            }
        )

        append_jsonl(MANUAL_RUNS_PATH, final)

        with STATE.lock:
            STATE.recent_manual_runs.append(final)
            STATE.recent_manual_runs = STATE.recent_manual_runs[-20:]
            if STATE.active_process is process:
                STATE.active_process = None
                STATE.active_run = None

    threading.Thread(target=finish, daemon=True).start()
    return record


def save_style_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = payload.get("config", payload)
    if not isinstance(config, dict):
        raise ValueError("投资风格配置必须是 JSON object")

    normalized = normalize_style_config(config)
    InvestmentStyle(config=normalized).validate()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STYLE_CONFIG_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path = write_style_md(WORKSPACE_DIR, normalized)

    return {
        "success": True,
        "config": normalized,
        "files": {
            "config": rel(STYLE_CONFIG_PATH),
            "style_md": rel(output_path),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AstraTradeDashboard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{now_str()}] {self.address_string()} {format % args}")

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"success": False, "error": message}, status=status)

    def read_body_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON object")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/snapshot":
            self.send_json(build_snapshot())
            return

        if path == "/api/style":
            self.send_json(style_payload())
            return

        if path == "/api/api-config":
            self.send_json(api_config_payload())
            return

        if path == "/api/scheduler":
            self.send_json(scheduler_status())
            return

        if path == "/api/scheduler-config":
            self.send_json(scheduler_config_payload())
            return

        if path == "/api/initialization":
            self.send_json(initialization_status())
            return

        if path == "/api/trace":
            run_id = parse_qs(parsed.query).get("run_id", [""])[0]
            self.send_json(read_trace_by_run_id(run_id))
            return

        if path == "/":
            self.serve_static(STATIC_DIR / "index.html")
            return

        if path.startswith("/static/"):
            target = STATIC_DIR / path.removeprefix("/static/")
            self.serve_static(target)
            return

        self.send_error_json("Not found", status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            body = self.read_body_json()

            if parsed.path == "/api/investment-style":
                self.send_json(save_style_config(body))
                return

            if parsed.path == "/api/manual-run":
                task = str(body.get("task", ""))
                max_steps = int(body.get("max_steps", 50))
                self.send_json({"success": True, "run": start_manual_run(task, max_steps=max_steps)})
                return

            if parsed.path == "/api/api-config":
                self.send_json(save_api_config(body))
                return

            if parsed.path == "/api/scheduler-config":
                self.send_json(save_scheduler_config(body))
                return

            if parsed.path == "/api/scheduler/start":
                self.send_json(start_scheduler(auto=False))
                return

            if parsed.path == "/api/scheduler/stop":
                self.send_json(stop_scheduler())
                return

            if parsed.path == "/api/initialize-workspace":
                self.send_json(start_initialization())
                return

            self.send_error_json("Not found", status=404)
        except Exception as exc:
            self.send_error_json(str(exc), status=400)

    def serve_static(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if not str(resolved).startswith(str(STATIC_DIR.resolve())):
                self.send_error_json("Forbidden", status=403)
                return
            if not resolved.exists() or not resolved.is_file():
                self.send_error_json("Not found", status=404)
                return

            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            body = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error_json(str(exc), status=500)


def load_manual_runs() -> None:
    STATE.recent_manual_runs = read_jsonl(MANUAL_RUNS_PATH, limit=20)


def load_initialization_runs() -> None:
    STATE.recent_initializations = read_jsonl(INITIALIZATION_RUNS_PATH, limit=20)


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    load_manual_runs()
    load_initialization_runs()
    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        start_scheduler(auto=True)
    except Exception as exc:
        print(f"[{now_str()}] failed to auto start scheduler: {exc}")

    print(f"AstraTrade dashboard running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
