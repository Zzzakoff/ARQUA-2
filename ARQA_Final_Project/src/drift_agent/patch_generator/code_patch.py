from __future__ import annotations

import libcst as cst

from drift_agent.types import PatchSpec


class AddFieldToModel(cst.CSTTransformer):
    def __init__(self, class_name: str, field_statement: str):
        self.class_name = class_name
        self.field_statement = field_statement
        self._in_target = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._in_target = node.name.value == self.class_name
        return True

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if not self._in_target:
            return updated_node
        new_field = cst.parse_statement(f"    {self.field_statement}\n")
        new_body = updated_node.body.with_changes(body=[*updated_node.body.body, new_field])
        return updated_node.with_changes(body=new_body)


def apply_code_patch(source: str, patch: PatchSpec) -> str:
    module = cst.parse_module(source)
    if patch.patch_type == "add_field":
        file_path, class_name = patch.location.split("::", 1)
        transformed = module.visit(AddFieldToModel(class_name, patch.content.strip()))
        return transformed.code
    return source

