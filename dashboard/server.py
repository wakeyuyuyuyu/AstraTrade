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
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv
load_dotenv()

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
ALARM_CONFIG_PATH = CONFIG_DIR / "alarm.json"
SCHEDULER_MODULE = "runtime.agent"
SCHEDULER_SOURCE_PATH = ROOT / "runtime" / "agent.py"
INITIALIZATION_SCRIPT_PATH = ROOT / "initialization.sh"
ENV_PATH = ROOT / ".env"
DEFAULT_AGENT_ENV_NAME = "stagent"
WORKSTREAM_ACTIVE_MAX_AGE_SECONDS = 30 * 60
BUILTIN_SUBAGENT_NAMES = {"holding_follow", "candidate_follow", "trading_diary"}


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
    env["PATH"] = f"{python_bin}{os.pathsep}{env.get('PATH', '')}"

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
    {
        "key": "TRADINGAGENTS_TOKEN",
        "label": "TradingAgents Token",
        "description": "TradingAgents 服务 Token，用于连接外部分析服务。",
        "secret": True,
    },
    {
        "key": "TRADINGAGENTS_API_URL",
        "label": "TradingAgents API URL",
        "description": "TradingAgents 服务地址。",
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


def mx_quota_payload() -> Dict[str, Any]:
    CANDIDATES_PATH = WORKSPACE_DIR / "pools" / "candidates.jsonl"
    HOLDINGS_PATH = WORKSPACE_DIR / "pools" / "holdings.jsonl"

    config = read_json(SCHEDULER_CONFIG_PATH, default_scheduler_config())
    if not isinstance(config, dict):
        config = default_scheduler_config()

    sessions = config.get("market_sessions") or []
    candidate_count = 0
    holding_count = 0

    if CANDIDATES_PATH.exists() and CANDIDATES_PATH.stat().st_size > 0:
        try:
            candidates = read_jsonl(CANDIDATES_PATH)
            candidate_count = len(candidates)
        except Exception:
            pass

    if HOLDINGS_PATH.exists() and HOLDINGS_PATH.stat().st_size > 0:
        try:
            holdings = read_jsonl(HOLDINGS_PATH)
            holding_count = len(holdings)
        except Exception:
            pass

    def parse_minutes(t: str) -> int:
        try:
            h, m = map(int, t.strip().split(":"))
            return h * 60 + m
        except Exception:
            return 0

    runs_per_day = 0
    session_details = []
    for session in sessions:
        start = parse_minutes(session.get("start", "09:30"))
        end = parse_minutes(session.get("end", "11:30"))
        interval = int(session.get("interval_minutes", 10))
        if interval <= 0:
            continue
        if end <= start:
            continue
        runs = (end - start) // interval
        runs_per_day += runs
        session_details.append({
            "start": session.get("start", "09:30"),
            "end": session.get("end", "11:30"),
            "interval_minutes": interval,
            "runs": runs,
        })

    candidate_calls_per_run = candidate_count
    total_daily = runs_per_day * candidate_calls_per_run

    promo_quota = 150
    normal_quota = 50

    return {
        "candidate_count": candidate_count,
        "holding_count": holding_count,
        "session_details": session_details,
        "runs_per_day": runs_per_day,
        "total_daily_calls": total_daily,
        "promo_quota": promo_quota,
        "normal_quota": normal_quota,
        "promo_sufficient": total_daily <= promo_quota,
        "normal_sufficient": total_daily <= normal_quota,
        "promo_remaining": max(0, promo_quota - total_daily),
        "normal_remaining": max(0, normal_quota - total_daily),
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
        fixed_job = {
            "name": clean_command_value(item.get("name"), f"固定任务 #{index} 名称"),
            "enabled": bool(item.get("enabled", True)),
            "time": validate_time_value(item.get("time"), f"固定任务 #{index} 时间"),
            "trigger_reason": clean_command_value(item.get("trigger_reason"), f"固定任务 #{index} 触发原因"),
        }
        command = str(item.get("command") or "").strip()
        if command:
            fixed_job["command"] = clean_command_value(command, f"固定任务 #{index} 命令")
        fixed_jobs.append(fixed_job)
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
        subagent = {
            "name": clean_command_value(item.get("name"), f"子 Agent #{index} 名称"),
            "enabled": bool(item.get("enabled", True)),
            "command": clean_command_value(item.get("command"), f"子 Agent #{index} 命令"),
        }
        trigger_time = str(item.get("time") or item.get("trigger_time") or "").strip()
        if trigger_time:
            subagent["time"] = validate_time_value(trigger_time, f"子 Agent #{index} 触发时间")
        subagents.append(subagent)
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

    unknown = sorted(incoming_names - current_names - BUILTIN_SUBAGENT_NAMES)
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


def parse_alarm_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def parse_alarm_time(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def format_alarm_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def next_recurring_alarm_time(alarm: Dict[str, Any], now: datetime) -> datetime | None:
    alarm_time = parse_alarm_time(alarm.get("trigger_time"))
    if alarm_time is None:
        return None

    weekdays = alarm.get("weekdays")
    if not isinstance(weekdays, list) or not weekdays:
        weekdays_set = {1, 2, 3, 4, 5, 6, 7}
    else:
        weekdays_set = {int(item) for item in weekdays if str(item).isdigit()}

    hour, minute = alarm_time
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        if day.isoweekday() not in weekdays_set:
            continue

        candidate = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
        if candidate > now:
            return candidate

    return None


def alarm_schedule_label(alarm: Dict[str, Any]) -> str:
    if alarm.get("run_once"):
        return str(alarm.get("trigger_datetime") or "--")

    weekdays = alarm.get("weekdays")
    weekday_label = ""
    if isinstance(weekdays, list) and weekdays:
        names = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}
        weekday_label = "周" + "/".join(names.get(int(item), str(item)) for item in weekdays if str(item).isdigit())

    return " · ".join(item for item in [str(alarm.get("trigger_time") or "--"), weekday_label] if item)


def alarm_item_payload(alarm: Dict[str, Any], global_enabled: bool, now: datetime) -> Dict[str, Any]:
    enabled = bool(alarm.get("enabled", True))
    run_once = bool(alarm.get("run_once"))
    next_at = parse_alarm_datetime(alarm.get("trigger_datetime")) if run_once else next_recurring_alarm_time(alarm, now)

    status = "scheduled"
    status_label = "待触发"
    if not global_enabled:
        status = "paused"
        status_label = "全局停用"
    elif not enabled:
        status = "disabled"
        status_label = "已停用"
    elif next_at is None:
        status = "invalid"
        status_label = "配置异常"
    elif run_once and next_at <= now:
        if alarm.get("triggered_at") or alarm.get("last_triggered_at") or alarm.get("fired_at"):
            status = "done"
            status_label = "已触发"
        else:
            status = "expired"
            status_label = "已过期"
    elif next_at <= now + timedelta(minutes=30):
        status = "soon"
        status_label = "即将触发"

    return {
        "alarm_id": alarm.get("alarm_id", ""),
        "name": alarm.get("name", "未命名 Alarm"),
        "enabled": enabled,
        "run_once": run_once,
        "task": alarm.get("task", ""),
        "schedule": alarm_schedule_label(alarm),
        "next_at": format_alarm_datetime(next_at),
        "status": status,
        "status_label": status_label,
    }


def alarm_payload() -> Dict[str, Any]:
    raw = read_json(ALARM_CONFIG_PATH, {"enabled": True, "alarms": []})
    if not isinstance(raw, dict):
        raw = {"enabled": True, "alarms": [], "error": "alarm.json 顶层必须是 object"}

    alarms = raw.get("alarms") if isinstance(raw.get("alarms"), list) else []
    global_enabled = bool(raw.get("enabled", True))
    now = datetime.now()
    items = [
        alarm_item_payload(alarm, global_enabled, now)
        for alarm in alarms
        if isinstance(alarm, dict)
    ]

    items.sort(
        key=lambda item: (
            item["status"] in {"disabled", "paused", "expired", "done", "invalid"},
            item.get("next_at") or "9999-99-99 99:99",
            item.get("name") or "",
        )
    )
    next_alarm = next((item for item in items if item["status"] in {"soon", "scheduled"}), None)

    return {
        "file": rel(ALARM_CONFIG_PATH),
        "enabled": global_enabled,
        "total": len(items),
        "active_count": sum(1 for item in items if item["status"] in {"soon", "scheduled"}),
        "next_alarm": next_alarm,
        "items": items,
        "updated_at": now_str(),
        "error": raw.get("_error") or raw.get("error", ""),
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
                "command": f"{AGENT_PYTHON} -m {SCHEDULER_MODULE}",
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
        "command": record.get("command", f"{AGENT_PYTHON} -m {SCHEDULER_MODULE}"),
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
        expected_command = f"{AGENT_PYTHON} -m {SCHEDULER_MODULE}"
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
    command = [AGENT_PYTHON, "-m", SCHEDULER_MODULE]
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


INACTIVE_HOLDING_STATUSES = {"sold", "closed", "cleared", "removed", "已卖出", "已清仓", "清仓"}


def holding_quantity(item: Dict[str, Any]) -> float:
    for key in ("count", "quantity", "shares"):
        value = item.get(key)
        if value is not None:
            return summarize_number(value)
    return 0.0


def holding_market_value(item: Dict[str, Any]) -> float:
    market_value = summarize_number(item.get("market_value"))
    if market_value:
        return market_value

    price = summarize_number(item.get("current_price") or item.get("price"))
    return holding_quantity(item) * price


def is_active_holding(item: Dict[str, Any]) -> bool:
    status = str(item.get("status") or "holding").strip().lower()
    if status in INACTIVE_HOLDING_STATUSES:
        return False
    return holding_quantity(item) > 0 or holding_market_value(item) > 0


def active_holdings(holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in holdings if is_active_holding(item)]


def reconcile_account_from_holdings(account: Dict[str, Any], holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    reconciled = dict(account) if isinstance(account, dict) else {}
    current_holdings = active_holdings(holdings)
    holdings_market_value = sum(holding_market_value(item) for item in current_holdings)

    account_total_asset = summarize_number(reconciled.get("total_asset"))
    account_cash = summarize_number(reconciled.get("available_cash", reconciled.get("cash")))

    total_asset = account_total_asset
    if total_asset <= 0:
        total_asset = account_cash + holdings_market_value
    if total_asset < holdings_market_value:
        total_asset = holdings_market_value + max(account_cash, 0)

    if total_asset > 0 and holdings_market_value <= total_asset:
        available_cash = max(total_asset - holdings_market_value, 0)
    else:
        available_cash = max(account_cash, 0)

    initial = float(reconciled.get("initial_cash", 1000000.0) or 1000000.0)
    reconciled["total_return_rate"] = round((total_asset - initial) / initial * 100, 2) if initial > 0 else 0.0

    reconciled["market_value"] = holdings_market_value
    reconciled["position_count"] = len(current_holdings)
    reconciled["total_asset"] = total_asset
    reconciled["available_cash"] = available_cash
    reconciled["cash"] = available_cash
    return reconciled


def pool_metrics(holdings: List[Dict[str, Any]], strategies: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    active_strategy_status = {"active", "pending", "watching", "trigger_ready", "待执行", "执行中"}
    candidate_status = {"watching", "ready", "trigger_ready", "待观察", "待触发"}
    current_holdings = active_holdings(holdings)

    return {
        "holdings_count": len(current_holdings),
        "holdings_market_value": sum(holding_market_value(item) for item in current_holdings),
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


def run_dir_activity_mtime(run_dir: Path) -> float:
    mtimes = [file_mtime(run_dir)]
    for path in run_dir.glob("step_*_output.json"):
        mtimes.append(file_mtime(path))
    for path in run_dir.glob("step_*_input.json"):
        mtimes.append(file_mtime(path))
    mtimes.append(file_mtime(run_dir / "run_summary.json"))
    return max(mtimes)


def latest_workstream_run_dir() -> Path | None:
    runs_dir = WORKSPACE_DIR / "logs" / "agent_runs"
    if not runs_dir.exists():
        return None

    dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not dirs:
        return None

    dirs.sort(key=run_dir_activity_mtime, reverse=True)
    return dirs[0]


def run_dir_is_recently_active(run_dir: Path) -> bool:
    if (run_dir / "run_summary.json").exists():
        return False
    activity_mtime = run_dir_activity_mtime(run_dir)
    if activity_mtime <= 0:
        return False
    return time.time() - activity_mtime <= WORKSTREAM_ACTIVE_MAX_AGE_SECONDS


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


def agent_workstream_entry(output_file: Path) -> Dict[str, Any] | None:
    data = read_json(output_file, {})
    if not isinstance(data, dict):
        return None

    parsed = data.get("parsed_output", {})
    if not isinstance(parsed, dict):
        return None

    output_type = parsed.get("type", "")
    step = data.get("step")
    timestamp = data.get("timestamp", "")

    if output_type == "thinking":
        text = str(parsed.get("next_action") or "").strip()
        if not text:
            return None
        return {
            "step": step,
            "timestamp": timestamp,
            "type": "thinking",
            "label": "思考",
            "text": text,
        }

    if output_type == "tool_call":
        text = str(parsed.get("reason") or "").strip()
        if not text:
            return None
        return {
            "step": step,
            "timestamp": timestamp,
            "type": "tool_call",
            "label": "执行工具",
            "tool": parsed.get("tool", ""),
            "text": text,
        }

    if output_type == "final":
        text = str(parsed.get("summary") or "").strip()
        if not text:
            return None
        return {
            "step": step,
            "timestamp": timestamp,
            "type": "final",
            "label": "完成",
            "text": text,
        }

    return None


def agent_workstream_payload(limit: int = 10) -> Dict[str, Any]:
    run_dir = latest_workstream_run_dir()
    if run_dir is None:
        return {
            "title": "工作流",
            "status": "idle",
            "status_label": "待命",
            "active": False,
            "run": None,
            "entries": [],
        }

    summary_path = run_dir / "run_summary.json"
    summary = read_json(summary_path, {})
    summary = summary if isinstance(summary, dict) else {}

    entries = [
        entry
        for entry in (agent_workstream_entry(path) for path in sorted(run_dir.glob("step_*_output.json")))
        if entry is not None
    ]

    summary_text = str(summary.get("summary") or summary.get("final_result", {}).get("summary", "")).strip()
    if summary_path.exists() and summary_text and not any(item.get("type") == "final" for item in entries):
        entries.append(
            {
                "step": summary.get("steps"),
                "timestamp": summary.get("timestamp", ""),
                "type": "final",
                "label": "完成",
                "text": summary_text,
            }
        )

    last_entry = entries[-1] if entries else {}
    has_summary = summary_path.exists()
    active = run_dir_is_recently_active(run_dir)
    status = "idle"
    status_label = "待命"

    if active:
        if last_entry.get("type") == "tool_call":
            step = last_entry.get("step")
            tool_result_path = run_dir / f"step_{int(step):03d}_tool_result.json" if isinstance(step, int) else None
            if tool_result_path and tool_result_path.exists():
                status = "thinking"
                status_label = "思考中"
            else:
                status = "tool_call"
                status_label = "执行工具"
        elif last_entry.get("type") == "thinking":
            status = "thinking"
            status_label = "思考中"
        else:
            status = "preparing"
            status_label = "准备中"
    elif last_entry.get("type") == "final":
        status = "final"
        status_label = "已完成"

    return {
        "title": "工作流",
        "status": status,
        "status_label": status_label,
        "active": active,
        "run": {
            "run_id": run_dir.name,
            "path": rel(run_dir),
            "mode": summary.get("mode", ""),
            "phase": summary.get("phase", ""),
            "timestamp": summary.get("timestamp", ""),
            "success": summary.get("success") if has_summary else None,
        },
        "entries": entries[-limit:],
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

    is_running = process is not None and process.poll() is None
    return {
        "running": is_running,
        "active": active if is_running else None,
        "recent": read_jsonl(MANUAL_RUNS_PATH, limit=10),
    }


def initialization_status() -> Dict[str, Any]:
    with STATE.lock:
        process = STATE.initialization_process
        active = STATE.active_initialization

    is_running = process is not None and process.poll() is None
    return {
        "running": is_running,
        "active": active if is_running else None,
        "recent": read_jsonl(INITIALIZATION_RUNS_PATH, limit=8),
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

    with INITIALIZATION_LOG_PATH.open("w", encoding="utf-8") as log_file:
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
        try:
            return_code = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait(timeout=5)
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

        if return_code == 0:
            with STATE.lock:
                STATE.recent_manual_runs = []
                STATE.recent_initializations = []

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
    reconciled_account = reconcile_account_from_holdings(account, holdings)

    return {
        "updated_at": now_str(),
        "account": reconciled_account,
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
        "agent_workstream": agent_workstream_payload(),
        "alarm": alarm_payload(),
    }


def _mxdata_query(tool_query: str, timeout: int = 30, max_retries: int = 3) -> Dict[str, Any]:
    """直接调用 mx-data API 并返回原始 JSON。

    失败时按 2/4/6 秒重试，最后给出具体诊断（SSL 阻断 / 超时 / 代理指引）。
    """
    api_key = os.environ.get("MX_APIKEY", "").strip()
    if not api_key:
        raise RuntimeError("MX_APIKEY 未配置")

    proxies = {}
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if https_proxy.strip():
        proxies["https"] = https_proxy.strip()

    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    headers = {"Content-Type": "application/json", "apikey": api_key}

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url, headers=headers, json={"toolQuery": tool_query},
                timeout=timeout, verify=False,
                proxies=proxies or None,
            )
            resp.raise_for_status()
            raw_text = resp.text.strip()
            if not raw_text:
                raise RuntimeError(f"API 返回空内容 (status={resp.status_code})")
            try:
                return resp.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(f"API 返回非 JSON 格式: {e} | 前200字: {raw_text[:200]}")
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)

    _raise_diagnostic_error(last_error, proxies, url)  # type: ignore[arg-type]


def _raise_diagnostic_error(last_error: Exception | None, proxies: dict, url: str) -> None:
    """根据错误类型和代理配置给出具体诊断。"""
    if last_error is None:
        raise RuntimeError(f"妙想 API 请求失败（无详细错误）")
    err_str = str(last_error)
    err_type = type(last_error).__name__

    if "SSL" in err_type or "ssl" in err_str.lower() or "UNEXPECTED_EOF" in err_str:
        if not proxies:
            raise RuntimeError(
                f"妙想 API 地址 {url} SSL 握手失败，可能是网络防火墙阻断了国内金融数据域名。\n"
                f"诊断：{last_error}\n"
                f"解决方案：设置 HTTPS_PROXY 环境变量（需要可访问国内站点的代理），\n"
                f"例如在 .env 文件中添加：HTTPS_PROXY=http://127.0.0.1:7890"
            )
        raise RuntimeError(
            f"妙想 API SSL 握手失败（已配置代理 {list(proxies.values())}）。\n"
            f"诊断：{last_error}\n"
            f"请检查代理是否可用或 MX_API_URL 是否正确。"
        )

    if "Timeout" in err_type or "timeout" in err_str.lower():
        raise RuntimeError(f"妙想 API 请求超时（已等待 30 秒）。请检查网络连接。\n诊断：{last_error}")

    raise RuntimeError(f"妙想 API 请求失败：{last_error}")


def _mxnews_query(query: str, count: int = 5) -> List[str]:
    """调用妙想新闻搜索 API，返回标题列表。"""
    api_key = os.environ.get("MX_APIKEY", "").strip()
    if not api_key:
        return []
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    body = {"query": query, "searchType": "NEWS", "count": count}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15, verify=False)
        data = resp.json()
        news_list = data.get("data", {}).get("data", {}).get("llmSearchResponse", {}).get("data", [])
        seen = set()
        result = []
        for n in news_list:
            if not isinstance(n, dict):
                continue
            title = str(n.get("title", "")).strip()
            if title and title not in seen:
                seen.add(title)
                result.append(title)
        return result
    except Exception:
        return []


def _query_macro_data() -> Dict[str, str]:
    """查询宏观数据（PMI, CPI, 国债收益率, 北向资金）存入 market_state 的宏字段。"""
    result: Dict[str, str] = {}
    queries = [
        ("pmi", "最新PMI数据 中国制造业采购经理指数"),
        ("cpi", "最新CPI数据 中国消费者物价指数"),
        ("bond_yield", "最新10年期国债收益率"),
        ("north_flow", "北向资金 净买入 沪深股通 资金流向"),
    ]
    for key, q in queries:
        try:
            titles = _mxnews_query(q, 3)
            if titles:
                result[key] = " | ".join(titles[:2])
        except Exception:
            pass
    return result


def _mxdata_extract_single_price(result: Any, symbol: str) -> Optional[float]:
    """
    从单个股票的 mx-data 响应中直接提取最新价。
    绕过 pivot table 解析，直接从 dto.table.f2 读取。
    返回 float 或 None。
    """
    try:
        if not isinstance(result, dict):
            return None
        inner = result.get("data")
        if not isinstance(inner, dict):
            return None
        inner2 = inner.get("data")
        if not isinstance(inner2, dict):
            return None
        search = inner2.get("searchDataResultDTO")
        if not isinstance(search, dict):
            return None
        for dto in search.get("dataTableDTOList", []):
            if not isinstance(dto, dict):
                continue
            raw_code = str(dto.get("code") or "").strip()
            raw_code = raw_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").zfill(6)
            if raw_code != symbol:
                continue
            table = dto.get("table")
            if not isinstance(table, dict):
                continue
            name_map = dto.get("nameMap", {})
            if not isinstance(name_map, dict):
                continue
            # name_map maps API field keys (f2) to field names (最新价)
            # Find which key maps to "最新价"
            target_key = None
            for api_key, label in name_map.items():
                if "最新价" in str(label) or "current" in str(label).lower():
                    target_key = api_key
                    break
            if not target_key:
                target_key = "f2"  # default
            vals = table.get(target_key)
            if isinstance(vals, list) and len(vals) > 0:
                raw_val = str(vals[0]).strip()
                if raw_val:
                    return float(raw_val)
    except Exception:
        pass
    return None


def _mxdata_extract_tables(result: Any) -> List[Dict[str, Any]]:
    """从 mx-data 原始响应中提取表格行，兼容 dataRowsList 和 pivot (table/headName) 两种格式。"""
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    if not isinstance(inner, dict):
        return []
    search = inner.get("searchDataResultDTO")
    if not isinstance(search, dict):
        return []
    tables: List[Dict[str, Any]] = []
    for dto in search.get("dataTableDTOList", []):
        if not isinstance(dto, dict):
            continue
        title = dto.get("title") or dto.get("inputTitle") or "table"
        rows = dto.get("dataRowsList") or dto.get("dataRows") or []
        if isinstance(rows, list) and rows:
            tables.append({"title": title, "rows": rows, "nameMap": dto.get("nameMap", {})})
            continue
        # pivot format: table.headName (dates) + indicator arrays
        table = dto.get("table")
        if not isinstance(table, dict):
            continue
        headName = table.get("headName", [])
        if not isinstance(headName, list) or not headName:
            continue
        name_map = dto.get("nameMap", {})
        if isinstance(name_map, list):
            name_map = {str(i): v for i, v in enumerate(name_map)}
        elif not isinstance(name_map, dict):
            name_map = {}
        pivot_code = str(dto.get("code") or dto.get("secCode") or "").strip()
        if pivot_code.endswith(".SH") or pivot_code.endswith(".SZ"):
            pivot_code = pivot_code[:-3]
        if pivot_code.endswith(".BJ"):
            pivot_code = pivot_code[:-3]
        pivot_code = pivot_code.zfill(6)
        # Build row-per-entry (one row per headName value)
        pivot_rows: List[Dict[str, str]] = []
        for idx, _ in enumerate(headName):
            row: Dict[str, str] = {":code": pivot_code}
            for key in table:
                if key == "headName":
                    row[":headName"] = str(headName[idx]) if idx < len(headName) else ""
                    continue
                vals = table[key]
                if isinstance(vals, list) and idx < len(vals):
                    label = name_map.get(key, name_map.get(str(key), str(key)))
                    row[str(label)] = str(vals[idx])
            pivot_rows.append(row)
        tables.append({"title": title, "rows": pivot_rows, "pivot": True})
    return tables


def _extract_sectors_from_news(news_titles: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """从新闻标题中提取板块关键词，返回 (hot_topics, watch_sectors, avoid_sectors)。"""
    keywords: Dict[str, str] = {
        "新能源": "新能源", "光伏": "新能源", "锂电池": "新能源", "储能": "新能源",
        "AI": "科技成长", "人工智能": "科技成长", "芯片": "科技成长", "半导体": "科技成长",
        "消费电子": "科技成长", "数字经济": "科技成长", "算力": "科技成长",
        "医药": "医药医疗", "医疗": "医药医疗", "生物": "医药医疗",
        "消费": "消费", "食品": "消费饮料", "白酒": "消费饮料",
        "金融": "金融", "银行": "金融", "券商": "金融", "保险": "金融",
        "地产": "地产基建", "基建": "地产基建",
        "汽车": "汽车", "新能源车": "汽车",
        "资源": "资源周期", "煤炭": "资源周期", "有色": "资源周期", "钢铁": "资源周期",
    }
    found: List[str] = []
    for title in news_titles:
        for kw, sector in keywords.items():
            if kw in title and sector not in found:
                found.append(sector)
    # 从新闻判断看多/看空
    watch: List[str] = []
    avoid: List[str] = []
    for title in news_titles:
        for kw, sector in keywords.items():
            if kw not in title:
                continue
            for bear_word in ("风险", "下跌", "回调", "减持", "利空", "警惕", "调整"):
                if bear_word in title and sector not in avoid and sector in found:
                    avoid.append(sector)
            for bull_word in ("拉升", "涨停", "领涨", "上涨", "突破", "利好", "大涨", "反弹"):
                if bull_word in title and sector not in watch:
                    watch.append(sector)
    hot = found[:5]
    return hot, watch, avoid


def _parse_ssz_indicators(raw: Any, idx: int = 0) -> Dict[str, str]:
    """解析上证指数 pivot 表格，取出指定位置（默认最新）的指标值。"""
    vals: Dict[str, str] = {}
    for tbl in _mxdata_extract_tables(raw):
        for row in tbl.get("rows", []):
            if isinstance(row, dict):
                for k, v in row.items():
                    if k != ":headName":
                        vals[k] = v
    return vals


def _refresh_market() -> Dict[str, Any]:
    """通过 mx-data 多重查询实时更新市场状态全部字段。"""
    now = now_str()
    today = now[:10]
    previous = read_json(WORKSPACE_DIR / "state" / "market_state.json", {})
    has_new_data = False

    evidence_lines: List[str] = []
    indices: Dict[str, str] = {}
    up_count = 0
    down_count = 0
    total_money_flow = 0.0

    # 查询1: 指数行情
    try:
        raw = _mxdata_query("上证指数 深证成指 创业板指 今日最新行情 最新价 涨跌幅 成交额")
        for tbl in _mxdata_extract_tables(raw):
            for row in tbl["rows"]:
                if isinstance(row, dict):
                    name = str(row.get("证券名称") or row.get("名称") or row.get("secName") or "").strip()
                    price = str(row.get("最新价") or row.get("收盘价") or row.get("currentPrice") or "").strip()
                    change = str(row.get("涨跌幅") or row.get("changePct") or "").strip()
                    vol = str(row.get("成交额") or row.get("amount") or "").strip()
                    if name:
                        parts = [name, price] if price else [name]
                        if change: parts.append(change)
                        if vol: parts.append(vol)
                        evidence_lines.append(" ".join(parts))
                        indices[name] = price
        if evidence_lines:
            has_new_data = True
    except Exception:
        pass

    # 查询2: 上涨家数 / 下跌家数 (pivot格式)
    try:
        raw2 = _mxdata_query("上证指数 涨跌家数")
        vals = _parse_ssz_indicators(raw2)
        up_str = vals.get("上涨家数", "")
        down_str = vals.get("下跌家数", "")
        if up_str:
            try: up_count = int(float(up_str))
            except: pass
        if down_str:
            try: down_count = int(float(down_str))
            except: pass
        if up_count > 0 or down_count > 0:
            evidence_lines.append(f"上涨{up_count}家 下跌{down_count}家")
            has_new_data = True
    except Exception:
        pass

    # 查询3: 主力资金净流入 (pivot格式)
    try:
        raw3 = _mxdata_query("上证指数 主力资金流入流出")
        vals3 = _parse_ssz_indicators(raw3)
        for k, v in vals3.items():
            if "净" in k or "净额" in k.replace("流入", "").replace("流出", ""):
                cleaned = v.replace(",", "").replace("亿", "0000").replace("万", "")
                # 尝试提取数值
                nums = re.findall(r"-?\d+\.?\d*", cleaned)
                if nums:
                    total_money_flow = float(nums[0])
                    if "万" in v:
                        total_money_flow *= 10000
                    elif "亿" not in v and "万" not in v and total_money_flow > 1000:
                        pass
        if total_money_flow != 0:
            flow_label = "净流入" if total_money_flow > 0 else "净流出"
            evidence_lines.append(f"主力资金{flow_label} {abs(total_money_flow):.0f}万元")
            has_new_data = True
    except Exception:
        pass

    # 查询4: 今日重要财经新闻
    key_events: List[str] = []
    try:
        news_titles = _mxnews_query("今日A股市场重要财经新闻", 8)
        if news_titles:
            key_events = news_titles[:8]
            has_new_data = True
    except Exception:
        pass

    # 从新闻标题提取板块信息
    hot_topics: List[str] = []
    watch_sectors: List[str] = []
    avoid_sectors: List[str] = []
    if key_events:
        hot_topics, watch_sectors, avoid_sectors = _extract_sectors_from_news(key_events)

    # 计算市场情绪
    sentiment_score = 50
    if up_count > 0 or down_count > 0:
        total = up_count + down_count
        if total > 0:
            sentiment_score = int(up_count / total * 100)
    elif indices:
        change_vals = []
        for v in indices.values():
            try:
                cv = float(v.replace("%", ""))
                change_vals.append(cv)
            except: pass
        if change_vals:
            avg_change = sum(change_vals) / len(change_vals)
            sentiment_score = max(0, min(100, 50 + int(avg_change * 5)))

    sentiment_label = "bullish" if sentiment_score >= 60 else "bearish" if sentiment_score <= 40 else "neutral"

    market_view = "neutral"
    if sentiment_score >= 65:
        market_view = "bullish"
    elif sentiment_score <= 35:
        market_view = "bearish"

    risk_level = "medium"
    if abs(sentiment_score - 50) > 30:
        risk_level = "low"
    elif abs(sentiment_score - 50) < 10:
        risk_level = "high"

    if not has_new_data:
        hot_topics = previous.get("hot_topics", hot_topics)
        watch_sectors = previous.get("watch_sectors", watch_sectors)
        avoid_sectors = previous.get("avoid_sectors", avoid_sectors)
        key_events = previous.get("key_events", key_events)
        sentiment_score = previous.get("market_sentiment", {}).get("score", sentiment_score)
        sentiment_label = previous.get("market_sentiment", {}).get("label", sentiment_label)
        market_view = previous.get("market_view", market_view)
        risk_level = previous.get("risk_level", risk_level)

    market_data = {
        "date": today,
        "market_view": market_view,
        "risk_level": risk_level,
        "summary": "；".join(evidence_lines) if evidence_lines else previous.get("summary", "无数据"),
        "hot_topics": hot_topics,
        "watch_sectors": watch_sectors,
        "avoid_sectors": avoid_sectors,
        "key_events": key_events,
        "macro": _query_macro_data(),
        "market_sentiment": {"score": sentiment_score, "label": sentiment_label},
        "updated_at": now,
        "evidence": [
            {"source": "mx-data", "summary": line}
            for line in (evidence_lines if evidence_lines else [previous.get("summary", "无数据")])
        ],
    }

    path = WORKSPACE_DIR / "state" / "market_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"indices": indices, "updated_at": now, "has_new_data": has_new_data}


def _refresh_account() -> Dict[str, Any]:
    """从妙想API同步持仓，API不可用时回退到本地文件计算。"""
    try:
        result = _refresh_account_mx()
        if isinstance(result, dict) and result.get("error"):
            return _refresh_account_local()
        return result
    except Exception:
        return _refresh_account_local()


def _refresh_account_mx() -> Dict[str, Any]:
    """从妙想API获取持仓和账户状态。"""
    api_key = os.environ.get("MX_APIKEY", "").strip()
    api_url = os.environ.get("MX_API_URL", "").strip()
    if not api_key or not api_url:
        raise RuntimeError("MX_APIKEY 或 MX_API_URL 未配置")

    proxies = {}
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if https_proxy.strip():
        proxies["https"] = https_proxy.strip()

    headers = {"apikey": api_key, "Content-Type": "application/json"}
    last_error: Optional[Exception] = None
    raw: Any = None
    for attempt in range(3):
        try:
            resp = requests.post(f"{api_url}/api/claw/mockTrading/positions", headers=headers, json={"moneyUnit": 1}, timeout=30, verify=False, proxies=proxies or None)
            resp.raise_for_status()
            raw_text = resp.text.strip()
            if not raw_text:
                raise RuntimeError(f"妙想 API 返回空内容 (status={resp.status_code})")
            try:
                raw = resp.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(f"妙想 API 返回非 JSON: {e} | 前200字: {raw_text[:200]}")
            if not isinstance(raw, dict):
                raise RuntimeError(f"妙想 API 返回非 dict: {type(raw).__name__}")
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep((attempt + 1) * 2)
    if raw is None:
        raise RuntimeError(f"妙想 API 请求失败: {last_error}")

    if not (raw.get("success") or str(raw.get("code")) == "200"):
        return {"error": f"API 返回失败: {raw.get('message')}"}

    data = raw.get("data")
    if not isinstance(data, dict):
        return {"error": "API 返回 data 字段缺失或非 dict"}

    pos_list = data.get("posList")
    if not isinstance(pos_list, list):
        pos_list = []
    return _save_account_from_positions(pos_list, data.get("totalAssets"), data.get("availBalance"))


def _refresh_account_local() -> Dict[str, Any]:
    """从本地文件计算持仓和账户状态。"""
    now = now_str()
    holdings = read_jsonl(WORKSPACE_DIR / "pools" / "holdings.jsonl")
    trades = read_jsonl(WORKSPACE_DIR / "logs" / "trades.jsonl")
    previous = read_json(WORKSPACE_DIR / "state" / "account_state.json", {})

    # 从交易记录计算现金余额
    initial_cash = previous.get("initial_cash", 1000000.0)
    cash = initial_cash
    for t in trades:
        if not isinstance(t, dict):
            continue
        side = str(t.get("side") or t.get("type", "")).lower()
        price = float(t.get("price", 0) or 0)
        quantity = int(t.get("count") or t.get("quantity", 0) or 0)
        if side in ("buy", "买入"):
            cash -= price * quantity
        elif side in ("sell", "卖出"):
            cash += price * quantity

    # 从mx-data逐个查询持仓最新价（批量查询返回交叉表格式，无法直接匹配代码）
    positions: List[Dict[str, Any]] = []
    total_market_value = 0.0
    total_pnl = 0.0
    prices: Dict[str, float] = {}
    if holdings:
        for h in holdings:
            if not isinstance(h, dict):
                continue
            symbol = str(h.get("symbol", "")).strip().zfill(6)
            if not symbol:
                continue
            try:
                raw = _mxdata_query(f"{symbol} 最新价")
                for tbl in _mxdata_extract_tables(raw):
                    for row in tbl.get("rows", []):
                        if not isinstance(row, dict):
                            continue
                        code = str(row.get(":code") or row.get("证券代码") or row.get("secuCode") or row.get("code") or "").strip().zfill(6)
                        if code != symbol:
                            # single-stock query: pivot row may have :code = symbol
                            # but the dto-level code is the primary; also check row keys
                            pass
                        for key in ("最新价", "收盘价", "currentPrice", "price"):
                            val = row.get(key)
                            if val is not None:
                                try:
                                    pv = float(val)
                                    if pv > 0:
                                        prices[code] = pv
                                except (ValueError, TypeError):
                                    pass
                                break
                # If pivot format didn't match via :code, try fallback from raw API
                if symbol not in prices:
                    fallback = _mxdata_extract_single_price(raw, symbol)
                    if fallback is not None:
                        prices[symbol] = fallback
            except Exception:
                pass
            time.sleep(0.3)

        for h in holdings:
            if not isinstance(h, dict):
                continue
            symbol = str(h.get("symbol", "")).strip().zfill(6)
            if not symbol:
                continue
            quantity = int(h.get("count") or h.get("quantity", 0) or 0)
            avg_cost = float(h.get("cost_price") or h.get("avg_cost", 0) or 0)
            current_price = prices.get(symbol, float(h.get("current_price", 0) or 0))
            mv = current_price * quantity
            pnl = (current_price - avg_cost) * quantity
            pnl_ratio = (current_price / avg_cost - 1) * 100 if avg_cost else 0

            entry = dict(h)
            entry.update({
                "current_price": current_price,
                "market_value": mv,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": round(pnl_ratio, 2),
                "updated_at": now_str(),
            })
            positions.append(entry)
            total_market_value += mv
            total_pnl += pnl

    available_cash = max(0, cash)
    total_asset = available_cash + total_market_value

    return _save_account_from_positions(positions, total_asset, available_cash)


def _save_account_from_positions(positions: List[Dict[str, Any]], total_asset: Any, available_cash: Any) -> Dict[str, Any]:
    """将持仓信息写入 account_state.json 和 holdings.jsonl。"""
    now = now_str()
    total_market_value = sum(p.get("market_value", 0) for p in positions if isinstance(p, dict))
    available = 0.0
    try:
        available = float(available_cash) if available_cash else 0.0
    except (ValueError, TypeError):
        available = 0.0
    total = 0.0
    try:
        total = float(total_asset) if total_asset else 0.0
    except (ValueError, TypeError):
        total = 0.0
    if total <= 0:
        total = available + total_market_value
    if available <= 0 and total >= total_market_value:
        available = total - total_market_value

    previous = read_json(WORKSPACE_DIR / "state" / "account_state.json", {})
    peak = max(float(previous.get("peak_value", 0) or 0), total)
    drawdown = round((peak - total) / peak * 100, 2) if peak > 0 else 0.0
    initial = float(previous.get("initial_cash", 1000000.0) or 1000000.0)
    total_return_rate = round((total - initial) / initial * 100, 2) if initial > 0 else 0.0

    account = {
        **previous,
        "mode": previous.get("mode") or "active",
        "cash": available,
        "total_asset": total,
        "peak_value": peak,
        "drawdown_pct": drawdown,
        "market_value": total_market_value,
        "available_cash": available,
        "position_count": sum(1 for p in positions if isinstance(p, dict) and (p.get("count") or p.get("quantity", 0) or 0) > 0 or p.get("market_value", 0) > 0),
        "positions": positions,
        "risk": previous.get("risk", {"max_position_ratio": 0.8, "max_single_stock_ratio": 0.2, "max_daily_trades": 5, "stop_trading": False}),
        "updated_at": now,
        "total_return_rate": total_return_rate,
    }

    account_path = WORKSPACE_DIR / "state" / "account_state.json"
    account_path.parent.mkdir(parents=True, exist_ok=True)
    account_path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    holdings_path = WORKSPACE_DIR / "pools" / "holdings.jsonl"
    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(holdings_path, "w", encoding="utf-8") as f:
        for p in positions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    return {"position_count": len(positions), "total_asset": total, "updated_at": now}


def _refresh_candidates() -> Dict[str, Any]:
    """通过一次 mx-data 批量查询所有候选股最新行情，更新 candidates.jsonl。"""
    candidates = read_jsonl(WORKSPACE_DIR / "pools" / "candidates.jsonl")
    if not candidates:
        return {"updated": 0, "total": 0, "message": "候选池为空"}

    symbol_to_cand: Dict[str, Dict[str, Any]] = {}
    query_names: List[str] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        symbol = str(cand.get("symbol") or "").strip()
        name = str(cand.get("name") or "").strip()
        if symbol:
            symbol_to_cand[symbol] = cand
            query_names.append(f"{name}({symbol})")

    if not symbol_to_cand:
        return {"updated": 0, "total": len(candidates), "message": "候选池无有效股票"}

    now = now_str()
    query_text = " ".join(query_names[:20]) + " 最新价"  # mx-data 单次最多约 20 只
    updated_count = 0

    try:
        raw = _mxdata_query(query_text)
        tables = _mxdata_extract_tables(raw)
        for tbl in tables:
            for row in tbl.get("rows", []):
                if not isinstance(row, dict):
                    continue
                code = str(row.get(":code") or row.get("证券代码") or row.get("secuCode") or row.get("code") or "").strip().zfill(6)
                if not code or code not in symbol_to_cand:
                    continue
                price_val = None
                for key in ("最新价", "收盘价", "currentPrice", "price"):
                    val = row.get(key)
                    if val is not None:
                        try:
                            price_val = float(val)
                        except (ValueError, TypeError):
                            pass
                        break
                if price_val is not None and price_val > 0:
                    cand = symbol_to_cand[code]
                    old_price = cand.get("current_price", 0)
                    cand["current_price"] = price_val
                    cand["updated_at"] = now
                    trigger = cand.get("trigger", {})
                    ttype = trigger.get("type", "")
                    tprice = trigger.get("price", 0)
                    if ttype in ("price_below", "price_above") and tprice > 0 and old_price > 0:
                        ratio = price_val / old_price
                        if ratio < 0.85 or ratio > 1.15:
                            new_tprice = round(price_val * (tprice / old_price), 2)
                            trigger["price"] = new_tprice
                    updated_count += 1
    except Exception:
        pass

    candidates_path = WORKSPACE_DIR / "pools" / "candidates.jsonl"
    with open(candidates_path, "w", encoding="utf-8") as f:
        for cand in candidates:
            f.write(json.dumps(cand, ensure_ascii=False) + "\n")

    return {"updated": updated_count, "total": len(candidates), "updated_at": now}


def refresh_all_data() -> Dict[str, Any]:
    """一键刷新全部关键数据：市场、账户、候选股。"""
    results: Dict[str, Any] = {"market": None, "account": None, "candidates": None}
    errors: List[str] = []

    try:
        results["market"] = _refresh_market()
    except Exception as e:
        errors.append(f"市场刷新失败: {e}")

    try:
        results["account"] = _refresh_account()
    except Exception as e:
        errors.append(f"账户刷新失败: {e}")

    try:
        results["candidates"] = _refresh_candidates()
    except Exception as e:
        errors.append(f"候选股刷新失败: {e}")

    return {
        "success": len(errors) == 0,
        "partial": len(errors) > 0 and any(r is not None for r in results.values()),
        "results": results,
        "errors": errors,
        "updated_at": now_str(),
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
        try:
            stdout, stderr = process.communicate(timeout=1800)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
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


RECOMMEND_PATH = WORKSPACE_DIR / "pools" / "scout_recommendations.jsonl"
CANDIDATES_PATH = WORKSPACE_DIR / "pools" / "candidates.jsonl"


def read_scout_recommendations() -> List[Dict[str, Any]]:
    return read_jsonl(RECOMMEND_PATH)


def write_scout_recommendations(items: List[Dict[str, Any]]) -> None:
    RECOMMEND_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECOMMEND_PATH, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _extract_price_from_mx(raw: Any) -> float:
    """从 mx-data 结果中提取最新价，兼容 dataRowsList 和 pivot 格式。"""
    for tbl in _mxdata_extract_tables(raw):
        for row in tbl.get("rows", []):
            if not isinstance(row, dict):
                continue
            # dataRowsList 格式：有独立代码列
            code = str(row.get("证券代码") or row.get("secuCode") or row.get("code") or "").strip()
            if code:
                for key in ("最新价", "收盘价", "currentPrice", "price"):
                    val = row.get(key)
                    if val is not None:
                        try:
                            parsed = float(val)
                            if parsed > 0:
                                return parsed
                        except (ValueError, TypeError):
                            pass
                continue
            # pivot 格式：nameMap 中的中文列名即指标名
            for key, val in row.items():
                if key == ":headName":
                    continue
                if "价" in key:
                    try:
                        parsed = float(str(val))
                        if 0 < parsed < 10000:
                            return parsed
                    except (ValueError, TypeError):
                        pass
            # fallback: 取任意数值
            for key, val in row.items():
                if key == ":headName":
                    continue
                try:
                    parsed = float(str(val))
                    if 0 < parsed < 10000:
                        return parsed
                except (ValueError, TypeError):
                    pass
    return 0.0


def accept_scout_recommendation(rec_id: str) -> Dict[str, Any]:
    recs = read_scout_recommendations()
    target = None
    for rec in recs:
        if rec.get("id") == rec_id:
            target = rec
            break
    if target is None:
        raise ValueError(f"未找到推荐: {rec_id}")
    if target.get("status") != "pending":
        raise ValueError(f"推荐 {rec_id} 状态不是 pending")

    now = now_str()
    symbol = target["symbol"]
    name = target["name"]
    initial_price = 0.0

    try:
        raw = _mxdata_query(f"{name}({symbol}) 最新价 收盘价")
        initial_price = _extract_price_from_mx(raw)
    except Exception:
        pass

    trigger_price = round(initial_price * 0.95, 2) if initial_price > 0 else 0
    stop_loss = round(initial_price * 0.85, 2) if initial_price > 0 else 0
    take_profit = round(initial_price * 1.3, 2) if initial_price > 0 else 0

    candidate = {
        "candidate_id": f"RECMD-{now[:10].replace('-', '')}-{rec_id.split('-')[-1]}",
        "symbol": symbol,
        "name": name,
        "reason": target.get("reason", ""),
        "source": "stock_scout",
        "tags": [],
        "score": 70,
        "status": "watching",
        "current_price": initial_price,
        "trigger": {"type": "price_below", "price": trigger_price, "condition": f"价格回调至{trigger_price}元以下时分批买入"},
        "buy_plan": {"planned_quantity": 0, "planned_cash": 0, "max_position_ratio": 0.5},
        "risk": {"stop_loss_price": stop_loss, "take_profit_price": take_profit},
        "valid_until": "",
        "added_at": now,
        "updated_at": now,
        "evidence": [{"source": "stock_scout", "summary": target.get("reason", "")}],
        "next_action": "等待价格回调触发",
        "notes": f"自动选股推荐：{target.get('reason', '')}",
    }

    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(candidate, ensure_ascii=False) + "\n")

    target["status"] = "accepted"
    target["accepted_at"] = now
    write_scout_recommendations(recs)

    return {"success": True, "candidate": candidate, "recommendation": target}


def reject_scout_recommendation(rec_id: str) -> Dict[str, Any]:
    recs = read_scout_recommendations()
    target = None
    for rec in recs:
        if rec.get("id") == rec_id:
            target = rec
            break
    if target is None:
        raise ValueError(f"未找到推荐: {rec_id}")

    target["status"] = "rejected"
    target["rejected_at"] = now_str()
    write_scout_recommendations(recs)

    return {"success": True, "recommendation": target}


def start_stock_scout() -> Dict[str, Any]:
    with STATE.lock:
        if STATE.active_process is not None and STATE.active_process.poll() is None:
            raise RuntimeError("已有进程正在运行，请等待本轮结束")

        record = {
            "id": f"scout_{int(time.time())}",
            "started_at": now_str(),
            "status": "running",
        }

        cmd = [AGENT_PYTHON, "-m", "subagent.stock_scout.exec_agent"]

        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=agent_subprocess_env(),
        )

        STATE.active_process = process
        STATE.active_run = record

    def finish() -> None:
        try:
            stdout, stderr = process.communicate(timeout=1800)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
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
        with STATE.lock:
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


def count_step_types(run_dir: Path) -> Dict[str, int]:
    counts = {"thinking": 0, "tool_call": 0, "final": 0, "error": 0}
    for output_file in sorted(run_dir.glob("step_*_output.json")):
        data = read_json(output_file, {})
        if not isinstance(data, dict):
            continue
        parsed = data.get("parsed_output", {})
        if not isinstance(parsed, dict):
            continue
        t = parsed.get("type", "")
        if t in counts:
            counts[t] += 1
    return counts


def build_agent_actions_log() -> Dict[str, Any]:
    """读取当天 agent_actions 日志内容。"""
    today = datetime.now().strftime("%Y-%m-%d")
    path = WORKSPACE_DIR.parent / "workspace" / "logs" / "agent_actions" / f"{today}.log"
    if not path.exists():
        path = WORKSPACE_DIR / "logs" / "agent_actions" / f"{today}.log"
    if not path.exists():
        return {"lines": [], "size": 0, "date": today}
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.strip().splitlines()
        max_lines = 500
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        tail.reverse()
        return {
            "lines": tail,
            "size": len(content),
            "date": today,
            "total": len(lines),
            "showing": len(tail),
        }
    except Exception as e:
        return {"lines": [f"[ERROR] failed to read log: {e}"], "size": 0, "date": today}


def build_runtime_logs() -> Dict[str, Any]:
    runs_dir = WORKSPACE_DIR / "logs" / "agent_runs"

    runs: List[Dict[str, Any]] = []
    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            summary = read_json(run_dir / "run_summary.json", {})
            if not isinstance(summary, dict) or not summary:
                continue
            step_counts = count_step_types(run_dir)
            started_at = summary.get("started_at", "")
            ended_at = summary.get("ended_at", "")
            duration = summary.get("duration_seconds")
            runs.append({
                "run_id": run_dir.name,
                "mode": summary.get("mode", ""),
                "phase": summary.get("phase", ""),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": duration,
                "success": summary.get("success"),
                "steps": summary.get("steps", 0),
                "tool_call_count": summary.get("tool_call_count", 0),
                "thinking_count": step_counts.get("thinking", 0),
                "error_count": step_counts.get("error", 0),
                "summary": summary.get("summary", ""),
            })

    runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)

    manual_runs = read_jsonl(MANUAL_RUNS_PATH, limit=50)
    scheduler_calls = parse_scheduler_calls(scheduler_log_paths(), limit=50)

    total = len(runs)
    success_count = sum(1 for r in runs if r.get("success") is True)
    failure_count = sum(1 for r in runs if r.get("success") is False)
    total_model_calls = sum(r.get("steps", 0) for r in runs)
    total_tool_calls = sum(r.get("tool_call_count", 0) for r in runs)
    total_errors = sum(r.get("error_count", 0) for r in runs)
    durations = [r["duration_seconds"] for r in runs if r.get("duration_seconds") is not None]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0

    agent_actions = build_agent_actions_log()

    return {
        "agent_actions": agent_actions,
        "summary": {
            "total_runs": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "total_model_calls": total_model_calls,
            "total_tool_calls": total_tool_calls,
            "total_errors": total_errors,
            "avg_duration_seconds": avg_duration,
        },
        "runs": runs,
        "manual_runs": [
            {
                "id": r.get("id"),
                "task": r.get("task"),
                "started_at": r.get("started_at"),
                "ended_at": r.get("ended_at"),
                "status": r.get("status"),
                "exit_code": r.get("exit_code"),
                "max_steps": r.get("max_steps"),
            }
            for r in reversed(manual_runs)
        ],
        "scheduler_calls": scheduler_calls,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AstraTradeDashboard/1.0"

    GET_ONLY_PATHS = frozenset({
        "/api/snapshot", "/api/style", "/api/api-config", "/api/scheduler",
        "/api/scheduler-config", "/api/initialization", "/api/mx-quota",
        "/api/scout-recommendations", "/api/runtime-logs", "/api/trace",
    })

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

        try:
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

            if path == "/api/mx-quota":
                self.send_json(mx_quota_payload())
                return

            if path == "/api/scout-recommendations":
                self.send_json({
                    "recommendations": read_scout_recommendations(),
                    "pending_count": sum(1 for r in read_scout_recommendations() if r.get("status") == "pending"),
                })
                return

            if path == "/api/runtime-logs":
                self.send_json(build_runtime_logs())
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
        except Exception:
            self.send_error_json("Internal error", status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path in self.GET_ONLY_PATHS:
            self.send_error_json("Method Not Allowed", status=405)
            return

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

            if parsed.path == "/api/stock-scout":
                self.send_json(start_stock_scout())
                return

            if parsed.path == "/api/scout-recommendations/accept":
                rec_id = str(body.get("id", "")).strip()
                if not rec_id:
                    self.send_error_json("缺少 id", status=400)
                    return
                self.send_json(accept_scout_recommendation(rec_id))
                return

            if parsed.path == "/api/scout-recommendations/reject":
                rec_id = str(body.get("id", "")).strip()
                if not rec_id:
                    self.send_error_json("缺少 id", status=400)
                    return
                self.send_json(reject_scout_recommendation(rec_id))
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

            if parsed.path == "/api/refresh-all":
                self.send_json(refresh_all_data())
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


def _auto_refresh_loop() -> None:
    while True:
        now = datetime.now()
        market_hours = (
            now.weekday() < 5
            and (
                (now.hour == 9 and now.minute >= 30)
                or now.hour == 10
                or (now.hour == 11 and now.minute <= 30)
                or now.hour == 13
                or now.hour == 14
                or (now.hour == 15 and now.minute == 0)
            )
        )
        if market_hours:
            try:
                refresh_all_data()
            except Exception:
                pass

        if market_hours:
            remaining = (30 - now.minute % 30) * 60 - now.second
            time.sleep(max(60, remaining))
        else:
            time.sleep(1800)


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    load_manual_runs()
    load_initialization_runs()

    threading.Thread(target=_auto_refresh_loop, daemon=True).start()

    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    scheduler_started = False
    while True:
        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except OSError as exc:
            print(f"[{now_str()}] failed to bind port {port}: {exc}", flush=True)
            return

        if not scheduler_started:
            try:
                start_scheduler(auto=True)
                scheduler_started = True
            except Exception as exc:
                print(f"[{now_str()}] failed to auto start scheduler: {exc}", flush=True)

        print(f"AstraTrade dashboard running at http://{host}:{port}", flush=True)

        try:
            server.serve_forever()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"[{now_str()}] server stopped unexpectedly: {exc}, restarting...", flush=True)
            server.server_close()
            continue

        break


def _singleton_mutex() -> bool:
    """Windows 全局命名互斥体，确保只有一个 dashboard 进程运行。
    返回 True 表示已有实例在运行（当前进程应退出）。
    """
    try:
        import ctypes as _c
        _INVALID_HANDLE = 0
        _ERROR_ALREADY_EXISTS = 183
        _name = "AstraTradeDashboard_Singleton"
        _h = _c.windll.kernel32.CreateMutexW(None, False, _name)
        if _h == _INVALID_HANDLE:
            return False
        if _c.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            _c.windll.kernel32.CloseHandle(_h)
            import atexit as _ae
            return True
        import atexit as _ae
        _ae.register(lambda: _c.windll.kernel32.CloseHandle(_h))
        return False
    except Exception:
        return False


if __name__ == "__main__":
    if _singleton_mutex():
        print(f"[{now_str()}] 检测到已有 dashboard 进程运行，退出避免重复。", flush=True)
    else:
        main()
