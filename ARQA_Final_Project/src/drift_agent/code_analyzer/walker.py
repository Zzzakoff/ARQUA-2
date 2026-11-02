from __future__ import annotations

import ast
import logging
import platform
from pathlib import Path

from drift_agent.code_analyzer.extractor import IncludeEdge, RouterDefinition, extract_endpoints
from drift_agent.code_analyzer.resolver import ClassInfo, ModelResolver, ModuleInfo
from drift_agent.errors import CodeAnalysisError
from drift_agent.types import NormalizedContract

LOGGER = logging.getLogger(__name__)


def analyze_codebase(project_root: str | Path) -> NormalizedContract:
    root = Path(project_root)
    if not root.exists():
        raise CodeAnalysisError(f"Source path does not exist: {root}")
    modules: dict[str, ModuleInfo] = {}
    files = [root] if root.is_file() else sorted(root.rglob("*.py"))
    source_root = root.parent if root.is_file() else root
    for file_path in files:
        relative = file_path.relative_to(source_root)
        if any(part in {".venv", "venv", ".git", "__pycache__", "site-packages", "node_modules"} for part in relative.parts):
            continue
        module_name = ".".join(relative.with_suffix("").parts)
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise CodeAnalysisError(f"Syntax error in {file_path}: {exc}") from exc
        module_info = ModuleInfo(module=module_name, filepath=file_path, tree=tree)
        _collect_imports(module_info)
        _collect_classes(module_info)
        modules[module_name] = module_info
    routers = _collect_routers(modules)
    includes = _collect_includes(modules)
    diagnostics: list[dict] = []
    for module in modules.values():
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call):
                reason = None
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"add_api_route", "add_route", "mount"}:
                    reason = "Programmatic route registration is not expanded"
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
                    if not node.args or any(kw.arg == "prefix" and not isinstance(kw.value, ast.Constant) for kw in node.keywords):
                        reason = "Computed router inclusion is not expanded"
                    elif _owner_to_key(module, node.args[0]) not in routers:
                        reason = "Included router could not be resolved"
                elif _name_from_expr(node.func) in {"FastAPI", "APIRouter"}:
                    if any(kw.arg == "prefix" and not isinstance(kw.value, ast.Constant) for kw in node.keywords):
                        reason = "Computed router prefix could not be resolved"
                if reason:
                    diagnostics.append({"scope": "routes", "message": reason, "source_file": str(module.filepath.relative_to(source_root)), "source_line": node.lineno})
    endpoints = extract_endpoints(source_root, modules, routers, includes, ModelResolver(modules), diagnostics)
    metadata = {
        "app_file": _guess_app_file(root, endpoints),
        "framework_version": "fastapi",
        "python_version": platform.python_version(),
        "project_root": str(root),
        "diagnostics": diagnostics,
        "analysis_complete": not diagnostics,
    }
    return NormalizedContract(endpoints=endpoints, source="code", metadata=metadata)


def _collect_imports(module_info: ModuleInfo) -> None:
    for node in ast.walk(module_info.tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level == 0:
                continue
            base_module = _resolve_module_reference(module_info.module, node.module, node.level)
            for alias in node.names:
                module_info.imports[alias.asname or alias.name] = (base_module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_info.imports[alias.asname or alias.name] = (alias.name, alias.name.split(".")[-1])


def _collect_classes(module_info: ModuleInfo) -> None:
    for node in module_info.tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [_name_from_expr(base) for base in node.bases if _name_from_expr(base)]
        is_model = any(base in {"BaseModel"} for base in bases)
        module_info.classes[node.name] = ClassInfo(
            module=module_info.module,
            filepath=module_info.filepath,
            node=node,
            bases=bases,
            is_pydantic_model=is_model or any(
                module_info.classes.get(base, ClassInfo("", Path(), node, [], False)).is_pydantic_model
                for base in bases
            ),
        )


def _collect_routers(modules: dict[str, ModuleInfo]) -> dict[str, RouterDefinition]:
    routers: dict[str, RouterDefinition] = {}
    for module_info in modules.values():
        for node in module_info.tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            constructor = _name_from_expr(node.value.func)
            if constructor not in {"FastAPI", "APIRouter"}:
                continue
            prefix = ""
            tags: list[str] = []
            for keyword in node.value.keywords:
                if keyword.arg in {"prefix", "root_path"} and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    prefix = keyword.value.value
                elif keyword.arg == "tags" and isinstance(keyword.value, ast.List):
                    tags = [
                        item.value
                        for item in keyword.value.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    ]
            key = f"{module_info.module}::{node.targets[0].id}"
            routers[key] = RouterDefinition(
                key=key,
                variable_name=node.targets[0].id,
                module=module_info.module,
                file_path=module_info.filepath,
                defined_at_line=node.lineno,
                instance_prefix=prefix,
                is_app=constructor == "FastAPI",
                tags=tags,
            )
    return routers


def _collect_includes(modules: dict[str, ModuleInfo]) -> list[IncludeEdge]:
    includes: list[IncludeEdge] = []
    for module_info in modules.values():
        for node in ast.walk(module_info.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
                continue
            parent_key = _owner_to_key(module_info, node.func.value)
            if not node.args:
                continue
            child_key = _owner_to_key(module_info, node.args[0])
            prefix = ""
            for keyword in node.keywords:
                if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    prefix = keyword.value.value
            includes.append(IncludeEdge(parent_key=parent_key, child_key=child_key, include_prefix=prefix))
    return includes


def _guess_app_file(root: Path, endpoints: dict[str, object]) -> str | None:
    if not endpoints:
        return None
    first_endpoint = next(iter(endpoints.values()))
    return getattr(first_endpoint, "source_file", None)


def _owner_to_key(module_info: ModuleInfo, owner: ast.AST) -> str:
    if isinstance(owner, ast.Name):
        imported = module_info.imports.get(owner.id)
        if imported is not None:
            return f"{imported[0]}::{imported[1]}"
        return f"{module_info.module}::{owner.id}"
    if isinstance(owner, ast.Attribute):
        if isinstance(owner.value, ast.Name):
            imported = module_info.imports.get(owner.value.id)
            if imported is not None:
                return f"{imported[0]}::{owner.attr}"
        return f"{module_info.module}::{owner.attr}"
    return f"{module_info.module}::app"


def _resolve_module_reference(current_module: str, module: str | None, level: int) -> str:
    if level == 0:
        return module or ""
    parts = current_module.split(".")
    if level:
        parts = parts[:-level]
    if module:
        parts.extend(module.split("."))
    return ".".join(part for part in parts if part)


def _name_from_expr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None

