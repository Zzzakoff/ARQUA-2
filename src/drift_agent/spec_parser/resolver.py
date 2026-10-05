from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from drift_agent.errors import UnsupportedFeatureError

LOGGER = logging.getLogger(__name__)


class SpecResolver:
    def __init__(self, document: dict[str, Any], spec_path: Path):
        self.document = document
        self.spec_path = spec_path
        self._cache: dict[str, Any] = {}

    def resolve_document(self) -> dict[str, Any]:
        return self._resolve_node(copy.deepcopy(self.document), stack=[])

    def _resolve_node(self, node: Any, stack: list[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return self._resolve_ref(str(node["$ref"]), stack)
            return {key: self._resolve_node(value, stack) for key, value in node.items()}
        if isinstance(node, list):
            return [self._resolve_node(item, stack) for item in node]
        return node

    def _resolve_ref(self, ref: str, stack: list[str]) -> Any:
        if not ref.startswith("#/"):
            raise UnsupportedFeatureError(f"external ref not supported: {ref}")
        if ref in stack:
            return {
                "type": "object",
                "description": f"[circular ref: {ref}]",
                "_analysis_note": f"Recursive reference {ref} is not expanded further",
            }
        if ref in self._cache:
            return copy.deepcopy(self._cache[ref])
        target = self._walk_pointer(ref)
        if target is None:
            LOGGER.warning("Missing ref target: %s", ref)
            return {"type": "unknown", "_analysis_note": f"Reference target not found: {ref}"}
        resolved = self._resolve_node(copy.deepcopy(target), [*stack, ref])
        self._cache[ref] = resolved
        return copy.deepcopy(resolved)

    def _walk_pointer(self, pointer: str) -> Any:
        node: Any = self.document
        for token in pointer.removeprefix("#/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                return None
            node = node[token]
        return node

