from __future__ import annotations

import json
import shlex
import subprocess
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]

CONFIG_PATH = ROOT / "config" / "scheduler.json"

LOG_DIR = ROOT / "workspace" / "logs" / "scheduler"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_hm(s: str) -> dtime:
    h, m = map(int, s.split(":"))
    return dtime(hour=h, minute=m)


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


def build_main_agent_command(base_command: str, trigger_reason: str, extra_instructions: str = "") -> str:
    command = (
        f"{base_command} "
        f"--mode scheduler "
        f"--trigger-reason {shlex.quote(trigger_reason)}"
    )

    if extra_instructions.strip():
        command += f" --extra-instructions {shlex.quote(extra_instructions.strip())}"

    return command


def run_command(task_name: str, command: str) -> int:
    write_log(f"RUN task={task_name} command={command}")

    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
    )

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
    base_command = job.get("command") or cfg.get("main_agent_command") or cfg.get("command", "python -m runtime.launcher")
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
    subagents = cfg.get("market_subagents", [])

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


def main() -> None:
    cfg = load_config()

    tz = ZoneInfo(
        cfg.get("timezone", "Asia/Shanghai")
    )

    interval = int(
        cfg.get("check_interval_seconds", 30)
    )

    last_run_keys: set[str] = set()

    write_log("scheduler started")

    while True:
        now = datetime.now(tz)
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        try:
            if not is_weekday(now, cfg):
                time.sleep(interval)
                continue

            fixed_job = get_fixed_job(now, cfg)
            if fixed_job is not None:
                key = f"fixed:{minute_key}:{fixed_job.get('name', '')}"

                if key not in last_run_keys:
                    last_run_keys.add(key)
                    run_fixed_main_agent(now, cfg, fixed_job)

            if in_market_schedule(now, cfg):
                key = f"market_subagents:{minute_key}"

                if key not in last_run_keys:
                    last_run_keys.add(key)
                    run_market_subagents(now, cfg)

            today_prefix = now.strftime("%Y-%m-%d")
            last_run_keys = {k for k in last_run_keys if today_prefix in k}

            time.sleep(interval)

        except Exception as e:
            write_log(f"ERROR {repr(e)}")
            time.sleep(interval)


if __name__ == "__main__":
    main()
