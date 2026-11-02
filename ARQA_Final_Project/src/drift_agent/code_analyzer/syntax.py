"""Small, non-executing helpers for Python annotations and field declarations."""

import ast


def name_of(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def keyword_value(node: ast.AST | None, name: str) -> ast.AST | None:
    if isinstance(node, ast.Call):
        return next((kw.value for kw in node.keywords if kw.arg == name), None)
    return None


def unwrap_annotated(node: ast.AST | None) -> tuple[ast.AST | None, list[ast.AST]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return node, []
    metadata: list[ast.AST] = []
    while isinstance(node, ast.Subscript) and name_of(node.value) == "Annotated":
        parts = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        metadata = parts[1:] + metadata
        node = parts[0]
    return node, metadata


def is_required(default: ast.AST | None) -> bool:
    if default is None:
        return True
    if isinstance(default, ast.Call) and name_of(default.func) in {
        "Field", "Query", "Header", "Cookie", "Path", "Body", "Form", "File"
    }:
        factory = keyword_value(default, "default_factory")
        if factory is not None and not (isinstance(factory, ast.Constant) and factory.value is None):
            return False
        default = default.args[0] if default.args else keyword_value(default, "default")
        if default is None:
            return True
    return isinstance(default, ast.Constant) and default.value is Ellipsis
