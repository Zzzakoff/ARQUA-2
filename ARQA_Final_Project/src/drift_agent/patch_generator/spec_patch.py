from __future__ import annotations

import io
from collections.abc import MutableSequence
from pathlib import Path

from ruamel.yaml import YAML

from drift_agent.types import PatchSpec


def _lookup(container: object, key: str) -> object:
    if isinstance(container, MutableSequence):
        return container[int(key)]
    return container[key]


def _assign(container: object, key: str, value: object) -> None:
    if isinstance(container, MutableSequence):
        container[int(key)] = value
    else:
        container[key] = value


def _split_location(document: object, location: str) -> list[str]:
    if not location:
        return []

    normalized = location.strip()
    for prefix in ("paths/", "path/"):
        if not normalized.startswith(prefix):
            continue
        path_location = normalized.removeprefix(prefix)
        if path_location.startswith("/"):
            return ["paths", *_split_openapi_path(document, path_location)]

    if normalized.startswith("/"):
        return ["paths", *_split_openapi_path(document, normalized)]

    return [part for part in normalized.split("/") if part]


def _split_openapi_path(document: object, location: str) -> list[str]:
    paths = document.get("paths", {}) if hasattr(document, "get") else {}
    for path_key in sorted(paths, key=len, reverse=True):
        if location == path_key:
            return [path_key]
        if location.startswith(f"{path_key}/"):
            rest = location[len(path_key) + 1 :]
            return [path_key, *[part for part in rest.split("/") if part]]
    return [part for part in location.split("/") if part]


def apply_spec_patches(spec_path: Path, patches: list[PatchSpec], errors: list[str] | None = None) -> str:
    yaml = YAML()
    yaml.preserve_quotes = True
    document = yaml.load(spec_path.read_text(encoding="utf-8"))
    for patch in patches:
        try:
            location_parts = _split_location(document, patch.location)
            parent = document
            for part in location_parts[:-1]:
                parent = _lookup(parent, part)
            key = location_parts[-1] if location_parts else None
            if patch.patch_type == "add_field":
                content = yaml.load(io.StringIO(patch.content))
                parent[key].update(content) if key and key in parent else parent.update(content)
            elif patch.patch_type == "remove_field":
                if key:
                    parent.pop(key, None)
            else:
                content = yaml.load(io.StringIO(patch.content))
                if key:
                    _assign(parent, key, content)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            message = f"Spec patch skipped at {patch.location!r}: {exc}"
            if errors is None:
                raise ValueError(message) from exc
            errors.append(message)
    buffer = io.StringIO()
    yaml.dump(document, buffer)
    return buffer.getvalue()
