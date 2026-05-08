from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from datetime import datetime


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
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
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
            self.write_file(path, content)
            return {
                "success": True,
                "tool": "write",
                "path": str(target),
                "bytes_written": len(content.encode("utf-8")),
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
            self.edit_file(path, old_text, new_text)
            return {
                "success": True,
                "tool": "edit",
                "path": str(target),
                "replaced": True,
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
            mode = self.add_file(path, content)
            return {
                "success": True,
                "tool": "add",
                "path": str(target),
                "mode": mode,
            }
        except Exception as exc:
            return {
                "success": False,
                "tool": "add",
                "path": path,
                "error": str(exc),
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
