from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drift_agent.code_analyzer.resolver import ModelResolver, ModuleInfo
from drift_agent.code_analyzer.syntax import is_required, keyword_value, unwrap_annotated
from drift_agent.types import EndpointContract, FieldSchema, ParameterSchema, RequestBodySchema, ResponseSchema

LOGGER = logging.getLogger(__name__)
PATH_PARAM_RE = re.compile(r"{([^}]+)}")
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
PARAMETER_MARKERS = {"Query", "Header", "Cookie", "Path", "Body", "Depends", "Security", "Form", "File"}


@dataclass
class RouterDefinition:
    key: str
    variable_name: str
    module: str
    file_path: Path
    defined_at_line: int
    instance_prefix: str = ""
    is_app: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class IncludeEdge:
    parent_key: str
    child_key: str
    include_prefix: str


def extract_endpoints(
    project_root: Path,
    modules: dict[str, ModuleInfo],
    routers: dict[str, RouterDefinition],
    includes: list[IncludeEdge],
    model_resolver: ModelResolver,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, EndpointContract]:
    prefix_map = _resolve_router_prefixes(routers, includes, diagnostics)
    endpoints: dict[str, EndpointContract] = {}
    for module_info in modules.values():
        for node in ast.walk(module_info.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                route = _extract_route_decorator(decorator)
                if route is None:
                    if diagnostics is not None and isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ROUTE_METHODS:
                        diagnostics.append({"scope": "routes", "message": "Route declaration could not be resolved statically", "source_file": str(module_info.filepath.relative_to(project_root)), "source_line": decorator.lineno})
                    continue
                owner_key = _resolve_router_key(module_info, route["owner"])
                if owner_key not in routers:
                    if diagnostics is not None:
                        diagnostics.append({"scope": "routes", "message": "Route owner could not be resolved as a FastAPI app or router", "source_file": str(module_info.filepath.relative_to(project_root)), "source_line": decorator.lineno})
                    continue
                prefixes = prefix_map.get(owner_key, [])
                for prefix in prefixes:
                    for method in route["methods"]:
                        notes: dict[str, str] = dict(route.get("analysis_notes", {}))
                        resolved_path = _normalize_path(f"{prefix}{route['path']}")
                        parameters, request_body = _extract_parameters(module_info, node, resolved_path, model_resolver, notes)
                        responses = _extract_responses(module_info, node, route, model_resolver)
                        tags = route["tags"] or routers.get(owner_key, RouterDefinition("", "", module_info.module, module_info.filepath, 0)).tags
                        endpoint = EndpointContract(
                            method=method,
                            path=resolved_path,
                            parameters=parameters,
                            request_body=request_body,
                            responses=responses,
                            tags=tags,
                            source_file=str(module_info.filepath.relative_to(project_root)),
                            source_line=decorator.lineno,
                            analysis_notes=notes,
                        )
                        endpoints[f"{method} {resolved_path}"] = endpoint
    return endpoints


def _resolve_router_prefixes(
    routers: dict[str, RouterDefinition],
    includes: list[IncludeEdge],
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    children_by_parent: dict[str, list[IncludeEdge]] = {}
    for edge in includes:
        children_by_parent.setdefault(edge.parent_key, []).append(edge)
    prefix_map: dict[str, list[str]] = {}
    roots = [key for key, router in routers.items() if router.is_app]
    for root_key in roots:
        prefix_map.setdefault(root_key, []).append(_normalize_path_fragment(routers[root_key].instance_prefix))
        stack = [(root_key, _normalize_path_fragment(routers[root_key].instance_prefix), (root_key,))]
        while stack:
            parent_key, parent_prefix, ancestry = stack.pop()
            for edge in children_by_parent.get(parent_key, []):
                if edge.child_key in ancestry:
                    if diagnostics is not None:
                        diagnostics.append({"scope": "routes", "message": "Cyclic router inclusion requires manual review", "source_file": None, "source_line": None})
                    continue
                child = routers.get(edge.child_key)
                if child is None:
                    continue
                combined = _normalize_path_fragment(f"{parent_prefix}{edge.include_prefix}{child.instance_prefix}")
                prefix_map.setdefault(edge.child_key, [])
                if combined not in prefix_map[edge.child_key]:
                    prefix_map[edge.child_key].append(combined)
                    stack.append((edge.child_key, combined, (*ancestry, edge.child_key)))
    if not roots:
        for key, router in routers.items():
            prefix_map.setdefault(key, [_normalize_path_fragment(router.instance_prefix)])
    return prefix_map


def _extract_route_decorator(decorator: ast.AST) -> dict[str, Any] | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = decorator.func.attr.lower()
    if method not in ROUTE_METHODS:
        return None
    keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
    path_node = decorator.args[0] if decorator.args else keywords.get("path")
    if not isinstance(path_node, ast.Constant) or not isinstance(path_node.value, str):
        LOGGER.warning("Skipping dynamic route decorator at line %s", getattr(decorator, "lineno", "?"))
        return None
    methods = [method.upper()]
    if method == "api_route":
        methods_node = keywords.get("methods")
        if methods_node is None or (isinstance(methods_node, ast.Constant) and methods_node.value is None):
            methods = ["GET"]
        elif isinstance(methods_node, (ast.List, ast.Tuple, ast.Set)) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in methods_node.elts
        ):
            # Keep results stable for sets and avoid duplicate endpoint extraction.
            methods = sorted({item.value.upper() for item in methods_node.elts}) or ["GET"]
        else:
            LOGGER.warning("Skipping dynamic route methods at line %s", decorator.lineno)
            return None
    route: dict[str, Any] = {
        "owner": decorator.func.value,
        "methods": methods,
        "path": path_node.value,
        "response_model": None,
        "status_code": _default_status_code(method),
        "tags": [],
        "analysis_notes": {},
    }
    for keyword in decorator.keywords:
        if keyword.arg == "response_model":
            route["response_model"] = keyword.value
        elif keyword.arg == "status_code":
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int) and not isinstance(keyword.value.value, bool):
                route["status_code"] = keyword.value.value
            elif not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None):
                route["analysis_notes"]["responses"] = "Computed status code could not be resolved statically"
        elif keyword.arg in {"responses", "response_class"}:
            route["analysis_notes"]["responses"] = "Additional responses or custom response class require manual review"
        elif keyword.arg == "dependencies":
            route["analysis_notes"]["parameters"] = "Dependency parameters are not expanded"
            route["analysis_notes"]["request_body"] = "Dependencies may contribute body fields"
        elif keyword.arg == "tags" and isinstance(keyword.value, ast.List):
            route["tags"] = [
                elt.value
                for elt in keyword.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return route


def _extract_parameters(
    module_info: ModuleInfo,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    resolved_path: str,
    model_resolver: ModelResolver,
    notes: dict[str, str] | None = None,
) -> tuple[list[ParameterSchema], RequestBodySchema | None]:
    notes = notes if notes is not None else {}
    path_params = set(PATH_PARAM_RE.findall(resolved_path))
    parameters: list[ParameterSchema] = []
    request_body = None
    args = [*function_node.args.posonlyargs, *function_node.args.args, *function_node.args.kwonlyargs]
    positional_defaults = [None] * (len(function_node.args.posonlyargs) + len(function_node.args.args) - len(function_node.args.defaults))
    positional_defaults.extend(function_node.args.defaults)
    kw_defaults = function_node.args.kw_defaults
    defaults = positional_defaults + kw_defaults
    for arg, default in zip(args, defaults):
        if arg.arg == "self":
            continue
        annotation, metadata = unwrap_annotated(arg.annotation)
        marker_node = default if _default_marker(default) in PARAMETER_MARKERS else next(
            (item for item in metadata if _default_marker(item) in PARAMETER_MARKERS), None
        )
        effective_default = default if default is not None else marker_node
        marker = _default_marker(marker_node)
        alias_node = keyword_value(marker_node, "alias")
        alias = alias_node.value if isinstance(alias_node, ast.Constant) and isinstance(alias_node.value, str) else arg.arg
        if alias_node is not None and alias == arg.arg and not isinstance(alias_node, ast.Constant):
            notes["parameters"] = "Computed parameter alias could not be resolved"
        if marker in {"Depends", "Security"}:
            notes["parameters"] = "Dependency parameters are not expanded"
            notes["request_body"] = "Dependencies may contribute body fields"
            continue
        if marker in {"Form", "File"}:
            notes["request_body"] = "Form/file body analysis is not supported"
            continue
        if alias in path_params or marker == "Path":
            field, _ = model_resolver.resolve_annotation(module_info.module, annotation, alias)
            field.required = True
            parameters.append(ParameterSchema(name=alias, location="path", required=True, schema=field))
            continue
        if marker == "Header":
            field, _ = model_resolver.resolve_annotation(module_info.module, annotation, alias)
            convert = keyword_value(marker_node, "convert_underscores")
            header_name = alias if alias_node is not None else (arg.arg if isinstance(convert, ast.Constant) and convert.value is False else arg.arg.replace("_", "-").title())
            parameters.append(
                ParameterSchema(
                    name=header_name,
                    location="header",
                    required=is_required(effective_default),
                    schema=field,
                )
            )
            continue
        if marker == "Cookie":
            field, _ = model_resolver.resolve_annotation(module_info.module, annotation, alias)
            parameters.append(
                ParameterSchema(
                    name=alias,
                    location="cookie",
                    required=is_required(effective_default),
                    schema=field,
                )
            )
            continue
        if marker == "Query":
            field, _ = model_resolver.resolve_annotation(module_info.module, annotation, alias)
            if field.type == "object":
                notes["parameters"] = "Query parameter models require expansion"
            parameters.append(
                ParameterSchema(
                    name=alias,
                    location="query",
                    required=is_required(effective_default),
                    schema=field,
                )
            )
            continue
        if marker == "Body" or _looks_like_body_model(module_info.module, annotation, model_resolver):
            if request_body is not None:
                LOGGER.warning("Multiple body parameters found in %s:%s; using first", module_info.filepath, function_node.lineno)
                notes["request_body"] = "Multiple body parameters require manual review"
                continue
            schema, _ = model_resolver.resolve_annotation(module_info.module, annotation, alias)
            embed = keyword_value(marker_node, "embed")
            if isinstance(embed, ast.Constant) and embed.value is True:
                schema.required = is_required(effective_default)
                schema = FieldSchema(name="body", type="object", properties={alias: schema})
            request_body = RequestBodySchema(
                required=is_required(effective_default),
                content_type="application/json",
                schema=schema,
            )
            continue
        field, _ = model_resolver.resolve_annotation(module_info.module, annotation, arg.arg)
        if field.analysis_note and field.type == "object":
            notes["parameters"] = "Unresolved argument may be a body model"
            notes["request_body"] = "Unresolved argument may be a body model"
        parameters.append(
            ParameterSchema(
                name=arg.arg,
                location="query",
                required=is_required(effective_default),
                schema=field,
            )
        )
    for parameter in parameters:
        parameter.schema.required = parameter.required
    return parameters, request_body


def _extract_responses(
    module_info: ModuleInfo,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    route: dict[str, Any],
    model_resolver: ModelResolver,
) -> dict[str, ResponseSchema]:
    status_code = str(route["status_code"])
    response_field = None
    if isinstance(route["response_model"], ast.Constant) and route["response_model"].value is None:
        response_field = FieldSchema(name="response", type="unknown", analysis_note="response_model=None disables the declared response contract")
    elif route["response_model"] is not None:
        response_field, _ = model_resolver.resolve_annotation(module_info.module, route["response_model"], "response")
    elif function_node.returns is not None:
        response_field, _ = model_resolver.resolve_annotation(module_info.module, function_node.returns, "response")
    else:
        response_field = _infer_dict_response(function_node)
    if response_field is None and status_code not in {"204", "304"}:
        response_field = FieldSchema(name="response", type="unknown", analysis_note="Response schema is not declared or statically inferable")
    responses = {
        status_code: ResponseSchema(status_code=status_code, content_type="application/json", schema=response_field),
        "422": ResponseSchema(
            status_code="422",
            content_type="application/json",
            schema=FieldSchema(
                name="validation_error",
                type="object",
                description="[FastAPI validation error response]",
                properties={},
            ),
        ),
    }
    return responses


def _infer_dict_response(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> FieldSchema | None:
    keys: dict[str, FieldSchema] = {}
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys[key.value] = FieldSchema(name=key.value, type="unknown")
    if not keys:
        return None
    return FieldSchema(name="response", type="object", properties=keys, analysis_note="Dictionary return keys were observed, but no response contract was declared")


def _resolve_router_key(module_info: ModuleInfo, owner: ast.AST) -> str:
    if isinstance(owner, ast.Name):
        imported = module_info.imports.get(owner.id)
        if imported:
            return f"{imported[0]}::{imported[1]}"
        return f"{module_info.module}::{owner.id}"
    if isinstance(owner, ast.Attribute):
        if isinstance(owner.value, ast.Name):
            imported = module_info.imports.get(owner.value.id)
            if imported:
                return f"{imported[0]}::{owner.attr}"
        return f"{module_info.module}::{owner.attr}"
    return f"{module_info.module}::app"


def _default_marker(default: ast.AST | None) -> str | None:
    if not isinstance(default, ast.Call):
        return None
    if isinstance(default.func, ast.Name):
        return default.func.id
    if isinstance(default.func, ast.Attribute):
        return default.func.attr
    return None


def _looks_like_body_model(module_name: str, annotation: ast.AST | None, model_resolver: ModelResolver) -> bool:
    if annotation is None:
        return False
    field, _ = model_resolver.resolve_annotation(module_name, annotation, "body")
    return field.type in {"object", "array"} and field.analysis_note is None


def _default_status_code(method: str) -> int:
    return 200


def _normalize_path(path: str) -> str:
    combined = path if path.startswith("/") else f"/{path}"
    while "//" in combined:
        combined = combined.replace("//", "/")
    if combined != "/" and combined.endswith("/"):
        combined = combined[:-1]
    return combined


def _normalize_path_fragment(path: str) -> str:
    if not path:
        return ""
    path = _normalize_path(path)
    return "" if path == "/" else path

