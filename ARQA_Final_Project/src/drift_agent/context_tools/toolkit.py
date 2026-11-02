from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from drift_agent.context_tools.coverage import get_test_coverage
from drift_agent.context_tools.git import get_commit_message, git_log
from drift_agent.context_tools.search import list_endpoints_with_tests, read_file_slice, search_codebase


class ContextToolkit:
    def __init__(self, project_root: str | Path, spec_path: str | Path):
        self.project_root = Path(project_root)
        self.spec_path = Path(spec_path)
        self._registry: dict[str, Callable[..., dict[str, Any]]] = {
            "git_log": self._git_log,
            "git_log_spec": self._git_log_spec,
            "get_commit_message": self._get_commit_message,
            "get_test_coverage": self._get_test_coverage,
            "search_codebase": self._search_codebase,
            "read_file_slice": self._read_file_slice,
            "list_endpoints_with_tests": self._list_endpoints_with_tests,
        }

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self._registry.get(name)
        if handler is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return handler(**args)
        except TypeError as exc:
            return {"error": f"invalid arguments for {name}: {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _git_log(self, filepath: str, n: int = 5) -> dict[str, Any]:
        return git_log(self.project_root, filepath=filepath, n=n)

    def _git_log_spec(self, n: int = 5) -> dict[str, Any]:
        return git_log(self.spec_path.parent, filepath=self.spec_path.name, n=n)

    def _get_commit_message(self, hash: str) -> dict[str, Any]:
        return get_commit_message(self.project_root, commit_hash=hash)

    def _get_test_coverage(self, endpoint: str | None = None, source_file: str | None = None) -> dict[str, Any]:
        return get_test_coverage(self.project_root, endpoint=endpoint, source_file=source_file)

    def _search_codebase(self, pattern: str, file_glob: str = "**/*.py", context_lines: int = 2) -> dict[str, Any]:
        return search_codebase(self.project_root, pattern=pattern, file_glob=file_glob, context_lines=context_lines)

    def _read_file_slice(self, filepath: str, start_line: int, end_line: int | None = None) -> dict[str, Any]:
        return read_file_slice(self.project_root, filepath=filepath, start_line=start_line, end_line=end_line)

    def _list_endpoints_with_tests(self) -> dict[str, Any]:
        return list_endpoints_with_tests(self.project_root)

