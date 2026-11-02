from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def search_codebase(project_root: Path, pattern: str, file_glob: str = "**/*.py", context_lines: int = 2) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for file_path in project_root.rglob("*"):
        if not file_path.is_file() or not fnmatch(str(file_path.relative_to(project_root)).replace("\\", "/"), file_glob):
            continue
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines, start=1):
            if pattern not in line:
                continue
            start = max(0, index - 1 - context_lines)
            end = min(len(lines), index + context_lines)
            matches.append(
                {
                    "file": str(file_path.relative_to(project_root)),
                    "line": index,
                    "match": line,
                    "context": lines[start:end],
                }
            )
            if len(matches) >= 50:
                return {"matches": matches, "total_matches": len(matches), "truncated": True, "error": None}
    return {"matches": matches, "total_matches": len(matches), "error": None}


def read_file_slice(project_root: Path, filepath: str, start_line: int, end_line: int | None = None) -> dict[str, Any]:
    start_line = max(1, int(start_line))
    end_line = min(end_line or (start_line + 30), start_line + 100)
    root = project_root.resolve()
    target = (root / filepath).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return {"filepath": filepath, "start_line": start_line, "end_line": end_line, "content": "", "error": "file outside project or not found"}
    if not target.exists():
        return {"filepath": filepath, "start_line": start_line, "end_line": end_line, "content": "", "error": "file not found"}
    lines = target.read_text(encoding="utf-8").splitlines()
    content_lines = []
    for line_number in range(start_line, min(end_line, len(lines)) + 1):
        content_lines.append(f"{line_number}: {lines[line_number - 1]}")
    return {"filepath": filepath, "start_line": start_line, "end_line": end_line, "content": "\n".join(content_lines), "error": None}


def list_endpoints_with_tests(project_root: Path) -> dict[str, Any]:
    endpoint_map: dict[str, list[str]] = {}
    tests_root = project_root / "tests"
    if not tests_root.exists():
        return {"endpoint_test_map": endpoint_map, "error": None}
    for test_file in tests_root.rglob("*.py"):
        if not (test_file.name.startswith("test_") or test_file.name.endswith("_test.py")):
            continue
        text = test_file.read_text(encoding="utf-8").lower()
        for method in ("get", "post", "put", "patch", "delete"):
            if method in text:
                endpoint_map.setdefault(method.upper(), []).append(str(test_file.relative_to(project_root)))
    return {"endpoint_test_map": endpoint_map, "error": None}

