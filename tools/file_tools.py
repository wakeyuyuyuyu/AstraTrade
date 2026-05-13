from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime


SCHEMA_SKILL_PATH = "skills/astra-trade-schema/SKILL.md"

SCHEMA_REFERENCES = {
    "state": "skills/astra-trade-schema/references/state.md",
    "pools": "skills/astra-trade-schema/references/pools.md",
    "logs": "skills/astra-trade-schema/references/logs.md",
    "reports": "skills/astra-trade-schema/references/reports.md",
}

COMMON_REFERENCE = "skills/astra-trade-schema/references/common.md"


class FileTools:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()

        if not self.workspace_root.exists():
            raise FileNotFoundError(f"workspace_root 不存在: {self.workspace_root}")
        if not self.workspace_root.is_dir():
            raise NotADirectoryError(f"workspace_root 不是目录: {self.workspace_root}")

    def _validate_path(self, file_path: str) -> Path:
        """确保路径位于 workspace 内。"""
        if not file_path or not file_path.strip():
            raise ValueError("path 不能为空")

        p = Path(file_path.strip())
        if not p.is_absolute():
            p = self.workspace_root / p

        p = p.resolve()

        if not str(p).startswith(str(self.workspace_root)):
            raise PermissionError(f"Path {p} is outside workspace")

        return p

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace_root))
        except ValueError:
            return str(path)

    def _schema_reference_for_path(self, path: Path) -> str | None:
        rel = self._relative_path(path)
        parts = Path(rel).parts
        if not parts:
            return None

        if parts[0] == "state":
            return SCHEMA_REFERENCES["state"]
        if parts[0] == "pools":
            return SCHEMA_REFERENCES["pools"]
        if parts[0] == "reports":
            return SCHEMA_REFERENCES["reports"]
        if parts[0] == "logs" and len(parts) > 1 and parts[1] == "agent_runs":
            return SCHEMA_REFERENCES["reports"]
        if parts[0] == "logs":
            return SCHEMA_REFERENCES["logs"]
        return None

    def _format_schema_error(self, path: Path, message: str, reference: str | None = None) -> str:
        ref = reference or self._schema_reference_for_path(path) or SCHEMA_SKILL_PATH
        return (
            f"格式错误: {message}。请先读取 `{SCHEMA_SKILL_PATH}`，"
            f"并根据 `{ref}`（必要时读取 `{COMMON_REFERENCE}`）确认格式后再重试。"
        )

    def _schema_error(self, path: Path, message: str, reference: str | None = None) -> None:
        raise ValueError(self._format_schema_error(path, message, reference=reference))

    def _require_keys(self, path: Path, data: Dict[str, Any], keys: List[str], context: str) -> None:
        missing = [key for key in keys if key not in data]
        if missing:
            self._schema_error(path, f"{context} 缺少必填字段: {', '.join(missing)}")

    def _require_list(self, path: Path, data: Dict[str, Any], keys: List[str], context: str) -> None:
        bad = [key for key in keys if key in data and not isinstance(data.get(key), list)]
        if bad:
            self._schema_error(path, f"{context} 字段必须是数组: {', '.join(bad)}")

    def _require_object(self, path: Path, value: Any, context: str) -> Dict[str, Any]:
        if not isinstance(value, dict):
            self._schema_error(path, f"{context} 必须是 JSON object")
        return value

    def _validate_json_text(self, path: Path, content: str) -> Any:
        try:
            return json.loads(content)
        except Exception as exc:
            self._schema_error(path, f"JSON 解析失败: {exc}")

    def _validate_jsonl_text(self, path: Path, content: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception as exc:
                self._schema_error(path, f"JSONL 第 {line_no} 行解析失败: {exc}")
            if not isinstance(obj, dict):
                self._schema_error(path, f"JSONL 第 {line_no} 行必须是 JSON object")
            records.append(obj)
        return records

    def _validate_state_record(self, path: Path, data: Dict[str, Any]) -> None:
        name = path.name
        if name == "account_state.json":
            self._require_keys(
                path,
                data,
                ["mode", "cash", "total_asset", "market_value", "available_cash", "position_count", "risk", "updated_at"],
                name,
            )
            risk = self._require_object(path, data.get("risk"), "account_state.risk")
            self._require_keys(
                path,
                risk,
                ["max_position_ratio", "max_single_stock_ratio", "max_daily_trades", "stop_trading"],
                "account_state.risk",
            )
            return

        if name == "market_state.json":
            self._require_keys(
                path,
                data,
                [
                    "date",
                    "market_view",
                    "risk_level",
                    "summary",
                    "hot_topics",
                    "watch_sectors",
                    "avoid_sectors",
                    "key_events",
                    "updated_at",
                    "evidence",
                ],
                name,
            )
            self._require_list(path, data, ["hot_topics", "watch_sectors", "avoid_sectors", "key_events", "evidence"], name)

    def _validate_pool_record(self, path: Path, data: Dict[str, Any]) -> None:
        name = path.name
        if name == "holdings.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "holding_id",
                    "symbol",
                    "name",
                    "count",
                    "availCount",
                    "cost_price",
                    "current_price",
                    "market_value",
                    "unrealized_pnl",
                    "unrealized_pnl_pct",
                    "strategy_id",
                    "status",
                    "opened_at",
                    "updated_at",
                    "notes",
                ],
                name,
            )
            return

        if name == "strategies.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "strategy_id",
                    "symbol",
                    "name",
                    "source",
                    "strategy_type",
                    "status",
                    "priority",
                    "entry_conditions",
                    "exit_conditions",
                    "stop_loss",
                    "position_plan",
                    "valid_until",
                    "created_at",
                    "updated_at",
                    "evidence",
                    "notes",
                ],
                name,
            )
            self._require_list(path, data, ["entry_conditions", "exit_conditions", "evidence"], name)
            self._require_object(path, data.get("stop_loss"), "strategy.stop_loss")
            self._require_object(path, data.get("position_plan"), "strategy.position_plan")
            return

        if name == "candidates.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "candidate_id",
                    "symbol",
                    "name",
                    "reason",
                    "source",
                    "tags",
                    "score",
                    "status",
                    "current_price",
                    "trigger",
                    "buy_plan",
                    "risk",
                    "valid_until",
                    "added_at",
                    "updated_at",
                    "evidence",
                    "next_action",
                    "notes",
                ],
                name,
            )
            self._require_list(path, data, ["tags", "evidence"], name)
            self._require_object(path, data.get("trigger"), "candidate.trigger")
            self._require_object(path, data.get("buy_plan"), "candidate.buy_plan")
            self._require_object(path, data.get("risk"), "candidate.risk")

    def _validate_log_record(self, path: Path, data: Dict[str, Any]) -> None:
        name = path.name
        if name == "agent_runs.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "timestamp",
                    "run_id",
                    "mode",
                    "trigger_reason",
                    "user_task",
                    "trigger_event",
                    "prompt_file",
                    "result_file",
                    "run_log_dir",
                    "success",
                    "phase",
                    "summary",
                ],
                name,
            )
            return

        if name == "events.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "event_id",
                    "timestamp",
                    "source",
                    "event_type",
                    "symbol",
                    "name",
                    "strategy_id",
                    "trigger_type",
                    "reason",
                    "trigger_event",
                    "status",
                    "run_id",
                ],
                name,
            )
            return

        if name == "trades.jsonl":
            self._require_keys(
                path,
                data,
                [
                    "trade_id",
                    "timestamp",
                    "mode",
                    "trigger_reason",
                    "symbol",
                    "name",
                    "side",
                    "quantity",
                    "price",
                    "amount",
                    "fee",
                    "strategy_id",
                    "decision_id",
                    "order_id",
                    "status",
                    "reason",
                    "created_by",
                ],
                name,
            )

    def _validate_report_record(self, path: Path, data: Dict[str, Any]) -> None:
        rel_parts = Path(self._relative_path(path)).parts
        if len(rel_parts) >= 4 and rel_parts[0] == "logs" and rel_parts[1] == "agent_runs":
            if path.name == "run_summary.json":
                self._require_keys(
                    path,
                    data,
                    ["timestamp", "success", "mode", "phase", "summary", "steps", "tool_call_count", "tool_call_history", "final_result"],
                    "run_summary.json",
                )
                self._require_list(path, data, ["tool_call_history"], "run_summary.json")
            return

        if path.name.endswith("_result.json"):
            self._require_keys(
                path,
                data,
                ["success", "type", "mode", "phase", "summary", "actions", "tool_calls", "decisions", "file_updates", "next_todos"],
                path.name,
            )
            self._require_list(path, data, ["actions", "tool_calls", "decisions", "file_updates", "next_todos"], path.name)

    def _validate_structured_file(self, path: Path) -> Dict[str, Any]:
        reference = self._schema_reference_for_path(path)
        if not reference:
            return {"schema_validated": False, "schema_reference": None}

        rel_parts = Path(self._relative_path(path)).parts
        suffix = path.suffix.lower()

        if not path.exists():
            self._schema_error(path, "写入后文件不存在", reference=reference)
        if not path.is_file():
            self._schema_error(path, "目标不是文件", reference=reference)

        content = path.read_text(encoding="utf-8")

        if suffix == ".jsonl":
            records = self._validate_jsonl_text(path, content)
            for record in records:
                if rel_parts[0] == "pools":
                    self._validate_pool_record(path, record)
                elif rel_parts[0] == "logs":
                    self._validate_log_record(path, record)
            return {"schema_validated": True, "schema_reference": reference, "records_checked": len(records)}

        if suffix == ".json":
            data = self._require_object(path, self._validate_json_text(path, content), path.name)
            if rel_parts[0] == "state":
                self._validate_state_record(path, data)
            elif rel_parts[0] == "reports" or (rel_parts[0] == "logs" and len(rel_parts) > 1 and rel_parts[1] == "agent_runs"):
                self._validate_report_record(path, data)
            return {"schema_validated": True, "schema_reference": reference, "records_checked": 1}

        return {"schema_validated": False, "schema_reference": reference}

    def _validate_structured_record(self, path: Path, record: Any) -> Dict[str, Any]:
        reference = self._schema_reference_for_path(path)
        if not reference or path.suffix.lower() != ".jsonl":
            return {"schema_validated": False, "schema_reference": reference}

        data = self._require_object(path, record, f"{path.name} append content")
        rel_parts = Path(self._relative_path(path)).parts
        if rel_parts[0] == "pools":
            self._validate_pool_record(path, data)
        elif rel_parts[0] == "logs":
            self._validate_log_record(path, data)

        return {"schema_validated": True, "schema_reference": reference, "records_checked": 1}

    def _snapshot_file(self, path: Path) -> tuple[bool, str]:
        if not path.exists():
            return False, ""
        if path.is_dir():
            raise IsADirectoryError(f"目标路径是目录，不能写入文件: {path}")
        return True, path.read_text(encoding="utf-8")

    def _rollback_file(self, path: Path, existed: bool, content: str) -> None:
        if existed:
            self.write_file(str(path), content)
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _rollback_validation_failure(self, path: Path, existed: bool, content: str, exc: Exception) -> str:
        try:
            self._rollback_file(path, existed, content)
        except Exception as rollback_exc:
            return f"{exc}；回滚失败: {rollback_exc}"
        return str(exc)

    def read_file(self, path: str, max_bytes: int = 200_000) -> str:
        p = self._validate_path(path)

        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not p.is_file():
            raise IsADirectoryError(f"目标不是文件: {p}")

        size = p.stat().st_size
        if size > max_bytes:
            raise ValueError(f"文件过大: {size} > {max_bytes}")

        return p.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        p = self._validate_path(path)

        if p.exists() and p.is_dir():
            raise IsADirectoryError(f"目标路径是目录，不能写入文件: {p}")

        p.parent.mkdir(parents=True, exist_ok=True)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(p.parent),
            prefix=".tmp_",
        )

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, str(p))
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def edit_file(self, path: str, old_text: str, new_text: str) -> None:
        """精确替换，只替换第一个匹配。"""
        if old_text == "":
            raise ValueError("oldText 不能为空")

        content = self.read_file(path)

        if old_text not in content:
            raise ValueError("oldText not found in file")

        updated = content.replace(old_text, new_text, 1)
        self.write_file(path, updated)

    def add_file(self, path: str, content: str) -> str:
        """
        向 JSON / JSONL 文件追加内容。

        - .jsonl: 追加一行 JSON
        - .json: 仅支持数组，append 一个对象
        """
        p = self._validate_path(path)

        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not p.is_file():
            raise IsADirectoryError(f"目标不是文件: {p}")

        try:
            obj = json.loads(content)
        except Exception as exc:
            raise ValueError(f"content 不是合法 JSON: {exc}")

        suffix = p.suffix.lower()

        if suffix == ".jsonl":
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
            return "jsonl_append"

        if suffix == ".json":
            raw = p.read_text(encoding="utf-8").strip()

            if not raw:
                data = []
            else:
                try:
                    data = json.loads(raw)
                except Exception as exc:
                    raise ValueError(f"现有 JSON 文件不是合法 JSON: {exc}")

            if not isinstance(data, list):
                raise ValueError("JSON 文件必须是数组才能使用 add")

            data.append(obj)
            self.write_file(path, json.dumps(data, ensure_ascii=False, indent=2))
            return "json_array_append"

        raise ValueError("add 只支持 .json 或 .jsonl 文件")

    def read(self, path: str) -> Dict[str, Any]:
        try:
            target = self._validate_path(path)
            content = self.read_file(path)
            return {
                "success": True,
                "tool": "read",
                "path": str(target),
                "content": content,
            }
        except Exception as exc:
            return {
                "success": False,
                "tool": "read",
                "path": path,
                "error": str(exc),
            }

    def write(self, path: str, content: str) -> Dict[str, Any]:
        try:
            target = self._validate_path(path)
            existed, previous_content = self._snapshot_file(target)
            self.write_file(path, content)
            try:
                validation = self._validate_structured_file(target)
            except Exception as validation_exc:
                error = self._rollback_validation_failure(target, existed, previous_content, validation_exc)
                return {
                    "success": False,
                    "tool": "write",
                    "path": str(target),
                    "validation_failed": True,
                    "error": error,
                }
            return {
                "success": True,
                "tool": "write",
                "path": str(target),
                "bytes_written": len(content.encode("utf-8")),
                **validation,
            }
        except Exception as exc:
            return {
                "success": False,
                "tool": "write",
                "path": path,
                "error": str(exc),
            }

    def edit(self, path: str, old_text: str, new_text: str) -> Dict[str, Any]:
        try:
            target = self._validate_path(path)
            existed, previous_content = self._snapshot_file(target)
            self.edit_file(path, old_text, new_text)
            try:
                validation = self._validate_structured_file(target)
            except Exception as validation_exc:
                error = self._rollback_validation_failure(target, existed, previous_content, validation_exc)
                return {
                    "success": False,
                    "tool": "edit",
                    "path": str(target),
                    "validation_failed": True,
                    "error": error,
                }
            return {
                "success": True,
                "tool": "edit",
                "path": str(target),
                "replaced": True,
                **validation,
            }
        except Exception as exc:
            return {
                "success": False,
                "tool": "edit",
                "path": path,
                "error": str(exc),
            }

    def add(self, path: str, content: str) -> Dict[str, Any]:
        try:
            target = self._validate_path(path)
            existed, previous_content = self._snapshot_file(target)
            validation: Dict[str, Any] | None = None

            if target.suffix.lower() == ".jsonl" and self._schema_reference_for_path(target):
                try:
                    record = json.loads(content)
                except Exception as exc:
                    raise ValueError(self._format_schema_error(target, f"content 不是合法 JSON: {exc}")) from exc
                validation = self._validate_structured_record(target, record)

            mode = self.add_file(path, content)
            if validation is None:
                try:
                    validation = self._validate_structured_file(target)
                except Exception as validation_exc:
                    error = self._rollback_validation_failure(target, existed, previous_content, validation_exc)
                    return {
                        "success": False,
                        "tool": "add",
                        "path": str(target),
                        "validation_failed": True,
                        "error": error,
                    }
            return {
                "success": True,
                "tool": "add",
                "path": str(target),
                "mode": mode,
                **validation,
            }
        except Exception as exc:
            error = str(exc)
            validation_failed = error.startswith("格式错误:")
            return {
                "success": False,
                "tool": "add",
                "path": path,
                "validation_failed": validation_failed,
                "error": error,
            }

    def write_memory(self, type: str, content: str) -> Dict[str, Any]:
        """
        写入当日记忆文件：

        memory/YYYY-MM-DD/
            summary.md
            plan.md
        """
        try:
            if type not in ["summary", "plan"]:
                raise ValueError("type 必须是 summary 或 plan")

            # 1. 获取今天日期
            today = datetime.now().strftime("%Y-%m-%d")

            # 2. 构建目录
            dir_path = self.workspace_root / "memory" / today
            dir_path.mkdir(parents=True, exist_ok=True)

            # 3. 文件名
            if type == "summary":
                filename = "summary.md"
            else:
                filename = "plan.md"

            target_path = dir_path / filename

            # 4. 写入（复用已有原子写）
            self.write_file(str(target_path), content)

            return {
                "success": True,
                "tool": "write_memory",
                "memory_type": type,
                "date": today,
                "path": str(target_path),
                "bytes_written": len(content.encode("utf-8")),
            }

        except Exception as exc:
            return {
                "success": False,
                "tool": "write_memory",
                "memory_type": type,
                "error": str(exc),
            }



if __name__ == "__main__":

    file_tools = FileTools(Path(__file__).resolve().parents[1] / "workspace")
    file_tools.write("state/runtime_state.json", json.dumps({"status": "sdasasdasd"}))
