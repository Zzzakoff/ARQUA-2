from __future__ import annotations

from typing import Any

from drift_agent.context_tools import ContextToolkit


def call_tool(toolkit: ContextToolkit, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return toolkit.call_tool(name, arguments)

