from __future__ import annotations

import os
import sys
import json
import shlex
import subprocess
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = Path(__file__).resolve().with_name("launcher.py")

CONFIG_PATH = ROOT / "config" / "scheduler.json"
ALARM_CONFIG_PATH = ROOT / "config" / "alarm.json"

LOG_DIR = ROOT / "workspace" / "logs" / "scheduler"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_alarm_config() -> dict:
    """
    读取 config/alarm.json。

    alarm.json 不存在时视为未配置 alarm，不报错。
    """
    if not ALARM_CONFIG_PATH.exists():
        return {"enabled": False, "alarms": []}

    try:
        with open(ALARM_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        write_log(f"ALARM_CONFIG_ERROR path={ALARM_CONFIG_PATH} error={repr(e)}")
        return {"enabled": False, "alarms": []}

    if not isinstance(data, dict):
        write_log("ALARM_CONFIG_ERROR reason=top_level_not_object")
        return {"enabled": False, "alarms": []}

    data.setdefault("enabled", True)
    data.setdefault("alarms", [])

    if not isinstance(data["alarms"], list):
        write_log("ALARM_CONFIG_ERROR reason=alarms_not_list")
        data["alarms"] = []

    return data


def save_alarm_config(data: dict) -> None:
    ALARM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(ALARM_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_hm(s: str) -> dtime:
    h, m = map(int, s.split(":"))
    return dtime(hour=h, minute=m)


def parse_alarm_datetime(s: str) -> datetime | None:
    """
    解析一次性 alarm 时间。

    标准格式：YYYY-MM-DD HH:MM:SS
    """
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def get_log_file(now: datetime) -> Path:
    return LOG_DIR / f"{now.strftime('%Y-%m-%d')}.log"


def write_log(msg: str) -> None:
    now = datetime.now()

    line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"

    print(line, end="")

    with open(get_log_file(now), "a", encoding="utf-8") as f:
        f.write(line)


def is_weekday(now: datetime, cfg: dict) -> bool:
    if not cfg.get("run_on_weekdays_only", True):
        return True

    return now.weekday() < 5


def get_fixed_job(now: datetime, cfg: dict) -> dict | None:
    cur_hm = now.strftime("%H:%M")

    for job in cfg.get("fixed_jobs", []):
        if not job.get("enabled", True):
            continue

        if job.get("time") == cur_hm:
            return job

    return None


def in_market_schedule(now: datetime, cfg: dict) -> bool:
    cur = now.time()

    for session in cfg.get("market_sessions", []):
        start = parse_hm(session["start"])
        end = parse_hm(session["end"])
        interval = int(session["interval_minutes"])

        if start <= cur <= end:
            minutes_from_start = (
                (cur.hour * 60 + cur.minute)
                - (start.hour * 60 + start.minute)
            )

            return minutes_from_start % interval == 0

    return False


def detect_trigger_reason(now: datetime) -> str:
    cur = now.time()

    if cur < dtime(9, 30):
        return "scheduled_premarket"
    if dtime(9, 30) <= cur < dtime(11, 30):
        return "scheduled_intraday"
    if dtime(11, 30) <= cur < dtime(13, 0):
        return "scheduled_lunch_break"
    if dtime(13, 0) <= cur < dtime(15, 0):
        return "scheduled_intraday"

    return "scheduled_postmarket"


def build_main_agent_command(
    base_command: str,
    trigger_reason: str,
    extra_instructions: str = "",
) -> str:
    command = (
        f"{base_command} "
        f"--mode scheduler "
        f"--trigger-reason {shlex.quote(trigger_reason)}"
    )

    if extra_instructions.strip():
        command += f" --extra-instructions {shlex.quote(extra_instructions.strip())}"

    return command


def build_alarm_agent_command(alarm: dict) -> str:
    """
    将 alarm 任务转为 manual 方式调用 launcher.py。

    等价于：
    python runtime/launcher.py --mode manual --trigger-reason alarm:<alarm_id> --task "<task>"
    """
    alarm_id = str(alarm.get("alarm_id", "unknown_alarm"))
    task = str(alarm.get("task", "")).strip()

    extra_instructions = (
        "本轮由 alarm 定时任务触发。"
        "请优先完成 alarm 中的 task，不要默认执行完整自动巡检。"
    )

    command = (
        f"{shlex.quote(sys.executable)} "
        f"{shlex.quote(str(LAUNCHER_PATH))} "
        f"--mode manual "
        f"--trigger-reason {shlex.quote(f'alarm:{alarm_id}')} "
        f"--task {shlex.quote(task)} "
        f"--extra-instructions {shlex.quote(extra_instructions)}"
    )

    return command


def normalize_command(command: str) -> list[str]:
    parts = shlex.split(command)

    if parts and parts[0] in {"python", "python3"}:
        parts[0] = sys.executable

    return parts


def run_command(task_name: str, command: str, timeout: int = 1800) -> int:
    """运行子进程并等待完成。默认 timeout=1800 秒（30分钟），超时后 SIGTERM 杀死进程。"""
    args = normalize_command(command)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    write_log(f"RUN task={task_name} command={shlex.join(args)}")

    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            close_fds=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        write_log(f"TIMEOUT task={task_name} exceeded {timeout}s")
        return -1
    except Exception as e:
        write_log(f"SUBPROCESS_ERROR task={task_name} error={repr(e)}")
        return -1

    if result.stdout:
        write_log(f"STDOUT BEGIN task={task_name}")
        write_log(result.stdout.strip())
        write_log(f"STDOUT END task={task_name}")

    if result.stderr:
        write_log(f"STDERR BEGIN task={task_name}")
        write_log(result.stderr.strip())
        write_log(f"STDERR END task={task_name}")

    write_log(f"EXIT_CODE task={task_name} code={result.returncode}")

    return result.returncode


def run_fixed_main_agent(now: datetime, cfg: dict, job: dict) -> None:
    base_command = (
        job.get("command")
        or cfg.get("main_agent_command")
        or cfg.get("command", "python -m runtime.launcher")
    )
    trigger_reason = job.get("trigger_reason") or detect_trigger_reason(now)
    extra_instructions = job.get("extra_instructions", "")
    name = job.get("name", "main_agent")

    command = build_main_agent_command(
        base_command=base_command,
        trigger_reason=trigger_reason,
        extra_instructions=extra_instructions,
    )

    write_log(
        f"FIXED_TRIGGER matched time={now.strftime('%Y-%m-%d %H:%M')} "
        f"name={name} reason={trigger_reason}"
    )

    run_command(name, command)


def run_market_subagents(now: datetime, cfg: dict) -> None:
    subagents = [
        subagent
        for subagent in cfg.get("market_subagents", [])
        if not str(subagent.get("time", "")).strip()
    ]

    if not subagents:
        write_log("MARKET_TRIGGER matched but no market_subagents configured")
        return

    write_log(
        f"MARKET_TRIGGER matched time={now.strftime('%Y-%m-%d %H:%M')} subagents={len(subagents)}"
    )

    for subagent in subagents:
        if not subagent.get("enabled", True):
            continue

        name = subagent.get("name", "unknown_subagent")
        command = subagent.get("command", "").strip()

        if not command:
            write_log(f"SKIP subagent={name} reason=empty_command")
            continue

        run_command(name, command)


def run_market_subagents(now: datetime, cfg: dict) -> None:
    subagents = [
        subagent
        for subagent in cfg.get("market_subagents", [])
        if not str(subagent.get("time", "")).strip()
    ]

    if not subagents:
        write_log("MARKET_TRIGGER matched but no market_subagents configured")
        return

    write_log(
        f"MARKET_TRIGGER matched time={now.strftime('%Y-%m-%d %H:%M')} subagents={len(subagents)}"
    )

    for subagent in subagents:
        if not subagent.get("enabled", True):
            continue

        name = subagent.get("name", "unknown_subagent")
        command = subagent.get("command", "").strip()

        if not command:
            write_log(f"SKIP subagent={name} reason=empty_command")
            continue

        run_command(name, command)


def run_market_scan(now: datetime, cfg: dict) -> None:
    """盘中扫描：调用 main_agent 执行全市场分析+候选股巡检。"""
    base_command = cfg.get("main_agent_command", "python -m runtime.launcher")
    trigger_reason = detect_trigger_reason(now)
    extra_instructions = (
        "本轮为盘中定时扫描。请执行以下操作：\n"
        "1. 读取 candidates.jsonl，查询所有候选股的最新行情\n"
        "2. 判断是否有候选股触发买入条件\n"
        "3. 读取 holdings.jsonl（如有持仓），检查止损止盈条件\n"
        "4. 更新 market_state.json 中的市场状态\n"
        "5. 记录分析和判断结果"
    )
    command = build_main_agent_command(
        base_command=base_command,
        trigger_reason=trigger_reason,
        extra_instructions=extra_instructions,
    )
    write_log(
        f"MARKET_SCAN triggered time={now.strftime('%Y-%m-%d %H:%M')} "
        f"reason={trigger_reason}"
    )
    run_command("market_scan", command)



def get_due_timed_subagents(now: datetime, cfg: dict) -> list[dict]:
    cur_hm = now.strftime("%H:%M")

    return [
        subagent
        for subagent in cfg.get("market_subagents", [])
        if subagent.get("enabled", True)
        and str(subagent.get("time", "")).strip() == cur_hm
    ]


def run_timed_subagent(now: datetime, subagent: dict) -> None:
    name = subagent.get("name", "unknown_subagent")
    command = subagent.get("command", "").strip()

    if not command:
        write_log(f"SKIP timed_subagent={name} reason=empty_command")
        return

    write_log(
        f"SUBAGENT_TRIGGER matched time={now.strftime('%Y-%m-%d %H:%M')} "
        f"name={name}"
    )

    run_command(name, command)


def get_alarm_key(now: datetime, alarm: dict) -> str:
    alarm_id = str(alarm.get("alarm_id", "unknown_alarm"))
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    return f"alarm:{minute_key}:{alarm_id}"


def is_alarm_due(now: datetime, alarm: dict) -> bool:
    """
    判断单个 alarm 是否到达触发时间。

    一次性 alarm:
    - run_once = true
    - trigger_datetime <= now 即触发
    - 触发后会自动从 alarm.json 中删除

    周期型 alarm:
    - run_once = false
    - 当前星期在 weekdays 中
    - 当前 HH:MM 等于 trigger_time
    """
    if not alarm.get("enabled", True):
        return False

    task = str(alarm.get("task", "")).strip()
    if not task:
        return False

    run_once = bool(alarm.get("run_once", False))

    if run_once:
        trigger_datetime = str(alarm.get("trigger_datetime", "")).strip()
        if not trigger_datetime:
            return False

        dt = parse_alarm_datetime(trigger_datetime)
        if dt is None:
            write_log(
                f"ALARM_INVALID_DATETIME "
                f"alarm_id={alarm.get('alarm_id', '')} value={trigger_datetime}"
            )
            return False

        # now 可能带 timezone，dt 是 naive；这里统一用本地 naive 比较
        now_naive = now.replace(tzinfo=None)
        return dt <= now_naive

    trigger_time = str(alarm.get("trigger_time", "")).strip()
    if not trigger_time:
        return False

    weekdays = alarm.get("weekdays", [])
    if not isinstance(weekdays, list):
        return False

    # Python: Monday=0；alarm: Monday=1
    today = now.weekday() + 1
    if today not in weekdays:
        return False

    return now.strftime("%H:%M") == trigger_time


def remove_once_alarm(alarm_data: dict, alarm_id: str) -> bool:
    """
    一次性 alarm 触发后从 config/alarm.json 中删除，避免 scheduler 重启后重复触发。
    """
    alarms = alarm_data.get("alarms", [])

    if not isinstance(alarms, list):
        return False

    before_count = len(alarms)

    alarm_data["alarms"] = [
        alarm
        for alarm in alarms
        if not (
            isinstance(alarm, dict)
            and alarm.get("alarm_id") == alarm_id
            and alarm.get("run_once", False)
        )
    ]

    removed = len(alarm_data["alarms"]) < before_count

    if removed:
        save_alarm_config(alarm_data)

    return removed


def run_alarm(now: datetime, alarm_data: dict, alarm: dict) -> None:
    alarm_id = str(alarm.get("alarm_id", "unknown_alarm"))
    name = str(alarm.get("name", alarm_id))
    task = str(alarm.get("task", "")).strip()

    if not task:
        write_log(f"ALARM_SKIP alarm_id={alarm_id} reason=empty_task")
        return

    write_log(
        f"ALARM_TRIGGER matched time={now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"alarm_id={alarm_id} name={name}"
    )

    command = build_alarm_agent_command(alarm)

    code = run_command(
        task_name=f"alarm:{name}",
        command=command,
    )

    if alarm.get("run_once", False):
        removed = remove_once_alarm(alarm_data, alarm_id)
        write_log(
            f"ALARM_ONCE_REMOVED alarm_id={alarm_id} "
            f"removed={removed} exit_code={code}"
        )


def run_due_alarms(now: datetime, last_run_keys: set[str]) -> None:
    alarm_data = load_alarm_config()

    if not alarm_data.get("enabled", True):
        return

    alarms = alarm_data.get("alarms", [])
    if not alarms:
        return

    for alarm in list(alarms):
        if not isinstance(alarm, dict):
            continue

        if not is_alarm_due(now, alarm):
            continue

        key = get_alarm_key(now, alarm)
        if key in last_run_keys:
            continue

        last_run_keys.add(key)
        run_alarm(now, alarm_data, alarm)


def main() -> None:
    cfg = load_config()

    try:
        from services.agent_logger import log
        log("scheduler", "RESTART", "scheduler process started")
    except Exception:
        pass

    tz = ZoneInfo(
        cfg.get("timezone", "Asia/Shanghai")
    )

    interval = int(
        cfg.get("check_interval_seconds", 30)
    )

    last_run_keys: set[str] = set()

    write_log(f"scheduler started python={sys.executable}")

    while True:
        now = datetime.now(tz)
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        try:
            # alarm 不强制受 scheduler 的 run_on_weekdays_only 限制；
            # 是否工作日触发，由 alarm 自己的 weekdays 决定。
            run_due_alarms(now, last_run_keys)

            if not is_weekday(now, cfg):
                time.sleep(interval)
                continue

            fixed_job = get_fixed_job(now, cfg)
            if fixed_job is not None:
                key = f"fixed:{minute_key}:{fixed_job.get('name', '')}"

                if key not in last_run_keys:
                    last_run_keys.add(key)
                    run_fixed_main_agent(now, cfg, fixed_job)

            for subagent in get_due_timed_subagents(now, cfg):
                key = f"subagent:{minute_key}:{subagent.get('name', '')}"

                if key not in last_run_keys:
                    last_run_keys.add(key)
                    run_timed_subagent(now, subagent)

            if in_market_schedule(now, cfg):
                key = f"market_scan:{minute_key}"

                if key not in last_run_keys:
                    last_run_keys.add(key)
                    run_market_scan(now, cfg)

            today_prefix = now.strftime("%Y-%m-%d")
            last_run_keys = {k for k in last_run_keys if today_prefix in k}

            time.sleep(interval)

        except Exception as e:
            write_log(f"ERROR {repr(e)}")
            time.sleep(interval)


if __name__ == "__main__":
    main()
