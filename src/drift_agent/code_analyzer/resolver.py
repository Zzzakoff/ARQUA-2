from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drift_agent.types import FieldSchema
from drift_agent.code_analyzer.syntax import is_required, keyword_value, name_of, unwrap_annotated

LOGGER = logging.getLogger(__name__)

PRIMITIVE_TYPE_MAP = {
    "str": ("string", None),
    "int": ("integer", None),
    "float": ("number", None),
    "bool": ("boolean", None),
    "Any": ("unknown", None),
    "EmailStr": ("string", "email"),
    "UUID": ("string", "uuid"),
    "datetime": ("string", "date-time"),
    "date": ("string", "date"),
}


@dataclass
class ClassInfo:
    module: str
    filepath: Path
    node: ast.ClassDef
    bases: list[str]
    is_pydantic_model: bool


@dataclass
class ModuleInfo:
    module: str
    filepath: Path
    tree: ast.Module
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    classes: dict[str, ClassInfo] = field(default_factory=dict)


class ModelResolver:
    def __init__(self, modules: dict[str, ModuleInfo]):
        self.modules = modules
        self.class_index = {
            (module.module, name): class_info
            for module in modules.values()
            for name, class_info in module.classes.items()
        }

    def resolve_model(self, module_name: str, class_name: str, required: bool = True, stack: tuple[str, ...] = ()) -> FieldSchema:
        class_info = self._find_class(module_name, class_name)
        if class_info is None:
            LOGGER.warning("Unable to resolve model %s from module %s", class_name, module_name)
            return FieldSchema(
                name=class_name,
                type="object",
                required=required,
                description=f"[unresolved: {class_name}]",
                analysis_note=f"Model {class_name} could not be resolved",
                properties={},
            )
        if f"{class_info.module}:{class_name}" in stack:
            return FieldSchema(
                name=class_name,
                type="object",
                required=required,
                description=f"[circular model: {class_name}]",
                analysis_note=f"Recursive model {class_name} is not expanded further",
                properties={},
            )
        stack = (*stack, f"{class_info.module}:{class_name}")
        properties: dict[str, FieldSchema] = {}
        model_note = None
        for base_name in class_info.bases:
            if base_name == "BaseModel":
                continue
            base_field = self.resolve_model(class_info.module, base_name, required=True, stack=stack)
            properties.update(base_field.properties or {})
            model_note = model_note or base_field.analysis_note
        for statement in class_info.node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                continue
            base_annotation, metadata = unwrap_annotated(statement.annotation)
            declaration = statement.value
            annotated_field = next((item for item in metadata if isinstance(item, ast.Call) and name_of(item.func) == "Field"), None)
            field_call = declaration if isinstance(declaration, ast.Call) and name_of(declaration.func) == "Field" else annotated_field
            alias_name = self._extract_alias(field_call)
            field_name = alias_name or statement.target.id
            annotation, nullable = self.resolve_annotation(class_info.module, base_annotation, field_name, stack)
            annotation.required = is_required(declaration if declaration is not None else annotated_field)
            annotation.nullable = annotation.nullable or nullable
            description = keyword_value(field_call, "description")
            if isinstance(description, ast.Constant) and isinstance(description.value, str):
                annotation.description = description.value
            if any(keyword_value(field_call, option) is not None for option in ("validation_alias", "serialization_alias")):
                model_note = "Separate validation/serialization aliases require manual review"
            properties[field_name] = annotation
        return FieldSchema(name=class_name, type="object", required=required, properties=properties, analysis_note=model_note)

    def resolve_annotation(self, module_name: str, annotation: ast.AST | None, field_name: str, stack: tuple[str, ...] = ()) -> tuple[FieldSchema, bool]:
        annotation, _ = unwrap_annotated(annotation)
        if annotation is None:
            return FieldSchema(name=field_name, type="unknown", required=False), False
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return FieldSchema(name=field_name, type="null", nullable=True), True
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return self._resolve_union(module_name, self._union_elements(annotation), field_name, stack)
        if isinstance(annotation, ast.Name):
            if annotation.id in PRIMITIVE_TYPE_MAP:
                type_name, fmt = PRIMITIVE_TYPE_MAP[annotation.id]
                return FieldSchema(name=field_name, type=type_name, format=fmt), False
            return self.resolve_model(module_name, annotation.id, required=False, stack=stack), False
        if isinstance(annotation, ast.Attribute):
            attr_name = annotation.attr
            if attr_name in PRIMITIVE_TYPE_MAP:
                type_name, fmt = PRIMITIVE_TYPE_MAP[attr_name]
                return FieldSchema(name=field_name, type=type_name, format=fmt), False
            return self.resolve_model(module_name, attr_name, required=False, stack=stack), False
        if isinstance(annotation, ast.Subscript):
            container = self._annotation_name(annotation.value)
            if container in {"Optional", "Union"}:
                inner = self._subscript_elements(annotation.slice)
                if container == "Optional":
                    inner = [*inner, ast.Constant(value=None)]
                return self._resolve_union(module_name, inner, field_name, stack)
            if container in {"list", "List"}:
                item_node = self._subscript_elements(annotation.slice)[0]
                item_field, _ = self.resolve_annotation(module_name, item_node, f"{field_name}[]", stack)
                return FieldSchema(name=field_name, type="array", items=item_field), False
            if container in {"dict", "Dict"}:
                item_elements = self._subscript_elements(annotation.slice)
                value_node = item_elements[1] if len(item_elements) > 1 else None
                value_name = self._annotation_name(value_node) if value_node is not None else "unknown"
                return (
                    FieldSchema(
                        name=field_name,
                        type="object",
                        description=f"[dict values: {value_name}]",
                        analysis_note="Dictionary keys are not statically enumerated",
                        properties={},
                    ),
                    False,
                )
            if container == "Literal":
                values = []
                for item in self._subscript_elements(annotation.slice):
                    if isinstance(item, ast.Constant):
                        values.append(item.value)
                types = {type(value) for value in values if value is not None}
                type_map = {str: "string", int: "integer", bool: "boolean", float: "number"}
                resolved_type = type_map.get(next(iter(types)), "unknown") if len(types) == 1 else "unknown"
                nullable = None in values
                return FieldSchema(name=field_name, type=resolved_type, enum=values, nullable=nullable), nullable
            inner_name = self._annotation_name(annotation)
            if inner_name:
                return FieldSchema(name=field_name, type="unknown", analysis_note=f"Unsupported annotation: {inner_name}"), False
        return FieldSchema(name=field_name, type="unknown"), False

    def _union_elements(self, node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._union_elements(node.left) + self._union_elements(node.right)
        return [node]

    def _resolve_union(self, module_name: str, variants: list[ast.AST], field_name: str, stack: tuple[str, ...]) -> tuple[FieldSchema, bool]:
        non_null = [item for item in variants if self._annotation_name(item) not in {"None", "NoneType"}]
        nullable = len(non_null) != len(variants)
        if len(non_null) == 1:
            field, _ = self.resolve_annotation(module_name, non_null[0], field_name, stack)
            field.nullable = field.nullable or nullable
            return field, field.nullable
        return FieldSchema(name=field_name, type="unknown", nullable=nullable, analysis_note="Multiple union variants require manual review"), nullable

    def _find_class(self, module_name: str, class_name: str) -> ClassInfo | None:
        direct = self.class_index.get((module_name, class_name))
        if direct is not None:
            return direct
        module_info = self.modules.get(module_name)
        if module_info is None:
            return None
        imported = module_info.imports.get(class_name)
        if imported is None:
            return None
        return self.class_index.get(imported)

    def _extract_alias(self, value: ast.AST | None) -> str | None:
        if not isinstance(value, ast.Call):
            return None
        if self._annotation_name(value.func) != "Field":
            return None
        for keyword in value.keywords:
            if keyword.arg == "alias" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
        return None

    def _annotation_name(self, node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            return self._annotation_name(node.value)
        if isinstance(node, ast.Constant) and node.value is None:
            return "None"
        return None

    def _subscript_elements(self, node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.Tuple):
            return list(node.elts)
        return [node]

