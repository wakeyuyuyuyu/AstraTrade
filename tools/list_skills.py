from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def extract_description(skill_md_path: Path) -> str:
    if not skill_md_path.exists():
        return "未找到 SKILL.md"

    text = skill_md_path.read_text(encoding="utf-8").strip()
    if not text:
        return "SKILL.md 为空"

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines[:30]:
        lower = line.lower()
        if lower.startswith("description:"):
            return line.split(":", 1)[1].strip() or "无描述"
        if line.startswith("描述："):
            return line.split("：", 1)[1].strip() or "无描述"
        if line.startswith("描述:"):
            return line.split(":", 1)[1].strip() or "无描述"

    for line in lines:
        if not line.startswith("#"):
            return line

    return lines[0]


def list_skills(skills_dir: str | Path) -> Dict[str, Any]:
    skills_path = Path(skills_dir)

    if not skills_path.exists():
        return {
            "success": False,
            "skills": [],
            "error": f"skills 目录不存在: {skills_path}",
        }

    if not skills_path.is_dir():
        return {
            "success": False,
            "skills": [],
            "error": f"skills 路径不是目录: {skills_path}",
        }

    skills: List[Dict[str, str]] = []

    for item in sorted(skills_path.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue

        skill_md = item / "SKILL.md"
        description = extract_description(skill_md)

        skills.append(
            {
                "name": item.name,
                "description": description,
                "path": str(item),
            }
        )

    return {
        "success": True,
        "count": len(skills),
        "skills": skills,
    }


if __name__ == "__main__":
    import json

    project_root = Path(__file__).resolve().parents[1]
    skills_dir = project_root / "skills"
    result = list_skills(skills_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))