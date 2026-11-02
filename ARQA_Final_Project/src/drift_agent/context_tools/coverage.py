from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import coverage as coverage_module


def get_test_coverage(project_root: Path, endpoint: str | None = None, source_file: str | None = None) -> dict[str, Any]:
    if source_file and not (project_root / source_file).resolve().is_relative_to(project_root.resolve()):
        return {"has_coverage": False, "coverage_percent": 0.0, "covered_lines": [], "uncovered_lines": [], "test_files": [], "error": "file outside project"}
    coverage_file = project_root / ".coverage"
    if coverage_file.exists() and source_file:
        cov = coverage_module.Coverage(data_file=str(coverage_file))
        cov.load()
        try:
            _, statements, excluded, missing, _ = cov.analysis2(str(project_root / source_file))
        except coverage_module.CoverageException:
            return {"has_coverage": False, "coverage_percent": 0.0, "covered_lines": [], "uncovered_lines": [], "test_files": [], "error": None}
        covered_lines = [line for line in statements if line not in missing and line not in excluded]
        percent = (len(covered_lines) / len(statements) * 100) if statements else 0.0
        return {
            "has_coverage": bool(statements),
            "coverage_percent": round(percent, 2),
            "covered_lines": covered_lines,
            "uncovered_lines": list(missing),
            "test_files": _discover_test_files(project_root, endpoint),
            "error": None,
        }
    coverage_xml = project_root / "coverage.xml"
    if coverage_xml.exists() and source_file:
        tree = ET.parse(coverage_xml)
        for class_node in tree.findall(".//class"):
            if class_node.attrib.get("filename") == source_file:
                lines = class_node.findall("./lines/line")
                covered = [int(line.attrib["number"]) for line in lines if int(line.attrib.get("hits", "0")) > 0]
                uncovered = [int(line.attrib["number"]) for line in lines if int(line.attrib.get("hits", "0")) == 0]
                total = len(covered) + len(uncovered)
                return {
                    "has_coverage": total > 0,
                    "coverage_percent": round((len(covered) / total * 100) if total else 0.0, 2),
                    "covered_lines": covered,
                    "uncovered_lines": uncovered,
                    "test_files": _discover_test_files(project_root, endpoint),
                    "error": None,
                }
    return {"has_coverage": False, "coverage_percent": 0.0, "covered_lines": [], "uncovered_lines": [], "test_files": [], "error": None}


def _discover_test_files(project_root: Path, endpoint: str | None) -> list[str]:
    tests_root = project_root / "tests"
    if not tests_root.exists():
        return []
    path_tokens = []
    method_token = ""
    if endpoint:
        method_token, _, path = endpoint.partition(" ")
        path_tokens = [token for token in path.strip("/").split("/") if token and not token.startswith("{")]
    matches: list[str] = []
    for test_file in tests_root.rglob("test_*.py"):
        text = test_file.read_text(encoding="utf-8")
        lowered = text.lower()
        if method_token and method_token.lower() not in lowered and not any(token in lowered for token in path_tokens):
            continue
        matches.append(str(test_file.relative_to(project_root)))
    return matches

