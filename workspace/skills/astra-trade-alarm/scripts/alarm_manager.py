#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def looks_like_project_root(path: Path) -> bool:
    """
    判断一个目录是否像 AstraTrade 项目根目录。

    项目根目录通常包含 config/、workspace/、runtime/、dashboard/、README.md、Makefile 等特征。
    不要求全部存在，避免在项目早期初始化阶段误判。
    """
    indicators = [
        path / "config",
        path / "workspace",
        path / "runtime",
        path / "dashboard",
        path / "README.md",
        path / "Makefile",
    ]
    return sum(p.exists() for p in indicators) >= 2


def find_project_root(start: Path) -> Path:
    """
    从 start 开始向上查找 AstraTrade 项目根目录。

    这样即使脚本从 workspace/、workspace/skills/、项目根目录、
    或 skill 目录内执行，也会尽量回到真正的项目根目录。
    """
    cur = start.expanduser().resolve()

    if cur.is_file():
        cur = cur.parent

    for path in [cur, *cur.parents]:
        if looks_like_project_root(path):
            return path

    # 兜底：如果当前路径本身是 workspace，则使用其父目录作为项目根目录
    if cur.name == "workspace":
        return cur.parent

    # 兜底：如果路径层级中包含 workspace，则使用 workspace 的父目录作为项目根目录
    for path in [cur, *cur.parents]:
        if path.name == "workspace":
            return path.parent

    raise SystemExit(
        f"无法从 {cur} 自动识别 AstraTrade 项目根目录。"
        "请在项目根目录执行脚本，或使用 --project-root 显式指定项目根目录。"
    )


def resolve_project_root(project_root: str) -> Path:
    """
    解析项目根目录。

    即使传入 --project-root . 且当前 cwd 是 workspace，
    也会自动向上找到真正的 AstraTrade 项目根目录。
    """
    raw = Path(project_root).expanduser()

    if raw.is_absolute():
        start = raw
    else:
        start = Path.cwd() / raw

    return find_project_root(start)


def alarm_path(project_root: str) -> Path:
    root = resolve_project_root(project_root)
    return root / "config" / "alarm.json"


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"enabled": True, "alarms": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"alarm.json 不是合法 JSON: {exc}")

    if not isinstance(data, dict):
        raise SystemExit("alarm.json 顶层必须是 object")

    data.setdefault("enabled", True)
    data.setdefault("alarms", [])

    if not isinstance(data["alarms"], list):
        raise SystemExit("alarm.json 中 alarms 必须是数组")

    return data


def save_config(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_time(value: str) -> str:
    if not TIME_RE.match(value):
        raise SystemExit("时间格式错误，应为 HH:MM，例如 09:10")
    return value


def validate_datetime(value: str) -> str:
    try:
        datetime.strptime(value, DATETIME_FMT)
    except ValueError:
        raise SystemExit("日期时间格式错误，应为 YYYY-MM-DD HH:MM:SS，例如 2026-05-12 09:20:00")
    return value


def parse_bool(value: str) -> bool:
    v = value.strip().lower()

    if v in {"true", "1", "yes", "y", "on", "启用", "开启"}:
        return True

    if v in {"false", "0", "no", "n", "off", "禁用", "关闭"}:
        return False

    raise SystemExit("布尔值格式错误，应为 true 或 false")


def parse_weekdays(value: str) -> List[int]:
    try:
        days = [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError:
        raise SystemExit("weekdays 格式错误，应为逗号分隔的数字，例如 1,2,3,4,5")

    if not days or any(day < 1 or day > 7 for day in days):
        raise SystemExit("weekdays 只能包含 1 到 7，1 表示周一，7 表示周日")

    seen: List[int] = []
    for day in days:
        if day not in seen:
            seen.append(day)

    return seen


def base_alarm_id_for_created_at() -> str:
    return "alarm_" + datetime.now().strftime("%Y%m%d%H%M%S")


def unique_alarm_id(
    base_id: str,
    alarms: List[Dict[str, Any]],
    exclude_alarm_id: Optional[str] = None,
) -> str:
    existing = {
        alarm.get("alarm_id")
        for alarm in alarms
        if alarm.get("alarm_id") != exclude_alarm_id
    }

    if base_id not in existing:
        return base_id

    idx = 2
    while True:
        candidate = f"{base_id}_{idx:02d}"
        if candidate not in existing:
            return candidate
        idx += 1


def find_alarm_index(alarms: List[Dict[str, Any]], alarm_id: str) -> int:
    for i, alarm in enumerate(alarms):
        if alarm.get("alarm_id") == alarm_id:
            return i

    raise SystemExit(f"未找到 alarm_id: {alarm_id}")


def validate_alarm(alarm: Dict[str, Any]) -> None:
    required = ["alarm_id", "name", "enabled", "task", "run_once"]
    missing = [key for key in required if key not in alarm]

    if missing:
        raise SystemExit(f"alarm 缺少字段: {missing}")

    if alarm.get("run_once"):
        if "trigger_datetime" not in alarm:
            raise SystemExit("一次性 alarm 必须包含 trigger_datetime")
        validate_datetime(str(alarm["trigger_datetime"]))
    else:
        if "trigger_time" not in alarm:
            raise SystemExit("周期型 alarm 必须包含 trigger_time")
        validate_time(str(alarm["trigger_time"]))

        if "weekdays" not in alarm:
            raise SystemExit("周期型 alarm 必须包含 weekdays")

        if not isinstance(alarm["weekdays"], list) or any(
            not isinstance(x, int) for x in alarm["weekdays"]
        ):
            raise SystemExit("weekdays 必须是整数数组")


def add_recurring(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)
    alarms = data["alarms"]

    trigger_time = validate_time(args.time)
    base_id = base_alarm_id_for_created_at()

    alarm = {
        "alarm_id": unique_alarm_id(base_id, alarms),
        "name": args.name,
        "enabled": not args.disabled,
        "trigger_time": trigger_time,
        "weekdays": parse_weekdays(args.weekdays),
        "task": args.task,
        "run_once": False,
    }

    validate_alarm(alarm)
    alarms.append(alarm)
    save_config(path, data)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "add-recurring",
                "alarm": alarm,
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def add_once(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)
    alarms = data["alarms"]

    trigger_datetime = validate_datetime(args.datetime)
    base_id = base_alarm_id_for_created_at()

    alarm = {
        "alarm_id": unique_alarm_id(base_id, alarms),
        "name": args.name,
        "enabled": not args.disabled,
        "trigger_datetime": trigger_datetime,
        "task": args.task,
        "run_once": True,
    }

    validate_alarm(alarm)
    alarms.append(alarm)
    save_config(path, data)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "add-once",
                "alarm": alarm,
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def update_alarm(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)
    alarms = data["alarms"]

    idx = find_alarm_index(alarms, args.alarm_id)
    alarm = dict(alarms[idx])
    old_id = alarm["alarm_id"]

    if args.name is not None:
        alarm["name"] = args.name

    if args.task is not None:
        alarm["task"] = args.task

    if args.enabled is not None:
        alarm["enabled"] = parse_bool(args.enabled)

    if args.weekdays is not None:
        alarm["weekdays"] = parse_weekdays(args.weekdays)

    if args.time is not None and args.datetime is not None:
        raise SystemExit("--time 和 --datetime 不能同时使用")

    if args.time is not None:
        trigger_time = validate_time(args.time)
        alarm.pop("trigger_datetime", None)
        alarm["trigger_time"] = trigger_time
        alarm.setdefault("weekdays", [1, 2, 3, 4, 5])
        alarm["run_once"] = False
        # alarm_id 表示创建 alarm 的时间，更新时间不改变 alarm_id

    if args.datetime is not None:
        trigger_datetime = validate_datetime(args.datetime)
        alarm.pop("trigger_time", None)
        alarm.pop("weekdays", None)
        alarm["trigger_datetime"] = trigger_datetime
        alarm["run_once"] = True
        # alarm_id 表示创建 alarm 的时间，更新时间不改变 alarm_id

    validate_alarm(alarm)
    alarms[idx] = alarm
    save_config(path, data)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "update",
                "old_alarm_id": old_id,
                "alarm": alarm,
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def delete_alarm(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)
    alarms = data["alarms"]

    idx = find_alarm_index(alarms, args.alarm_id)
    removed = alarms.pop(idx)

    save_config(path, data)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "delete",
                "removed": removed,
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def set_global(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)

    data["enabled"] = parse_bool(args.enabled)

    save_config(path, data)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "set-global",
                "enabled": data["enabled"],
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def list_alarms(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)

    print(
        json.dumps(
            {
                "ok": True,
                "path": str(path),
                "config": data,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def validate_config(args: argparse.Namespace) -> None:
    path = alarm_path(args.project_root)
    data = load_config(path)

    ids = []
    for alarm in data["alarms"]:
        validate_alarm(alarm)
        ids.append(alarm["alarm_id"])

    if len(ids) != len(set(ids)):
        raise SystemExit("alarm_id 存在重复")

    print(
        json.dumps(
            {
                "ok": True,
                "action": "validate",
                "count": len(ids),
                "path": str(path),
            },
            ensure_ascii=False,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 AstraTrade 项目根目录下的 config/alarm.json")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_project_root(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--project-root",
            default=".",
            help="AstraTrade 项目根目录，默认当前目录；脚本会自动向上识别真实项目根目录",
        )

    p = sub.add_parser("add-recurring", help="新增周期型 alarm")
    add_project_root(p)
    p.add_argument("--time", required=True, help="触发时间，格式 HH:MM")
    p.add_argument("--weekdays", default="1,2,3,4,5", help="生效星期，例如 1,2,3,4,5")
    p.add_argument("--name", required=True, help="alarm 名称")
    p.add_argument("--task", required=True, help="传给主 Agent 的 manual 任务")
    p.add_argument("--disabled", action="store_true", help="创建后默认关闭")
    p.set_defaults(func=add_recurring)

    p = sub.add_parser("add-once", help="新增一次性 alarm")
    add_project_root(p)
    p.add_argument("--datetime", required=True, help="触发时间，格式 YYYY-MM-DD HH:MM:SS")
    p.add_argument("--name", required=True, help="alarm 名称")
    p.add_argument("--task", required=True, help="传给主 Agent 的 manual 任务")
    p.add_argument("--disabled", action="store_true", help="创建后默认关闭")
    p.set_defaults(func=add_once)

    p = sub.add_parser("update", help="更新 alarm")
    add_project_root(p)
    p.add_argument("--alarm-id", required=True)
    p.add_argument("--name")
    p.add_argument("--task")
    p.add_argument("--enabled")
    p.add_argument("--time")
    p.add_argument("--datetime")
    p.add_argument("--weekdays")
    p.set_defaults(func=update_alarm)

    p = sub.add_parser("delete", help="删除 alarm")
    add_project_root(p)
    p.add_argument("--alarm-id", required=True)
    p.set_defaults(func=delete_alarm)

    p = sub.add_parser("set-global", help="启用或关闭整个 alarm 系统")
    add_project_root(p)
    p.add_argument("--enabled", required=True)
    p.set_defaults(func=set_global)

    p = sub.add_parser("list", help="查看当前 alarm 配置")
    add_project_root(p)
    p.set_defaults(func=list_alarms)

    p = sub.add_parser("validate", help="校验 alarm.json")
    add_project_root(p)
    p.set_defaults(func=validate_config)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except BrokenPipeError:
        sys.exit(1)


if __name__ == "__main__":
    main()