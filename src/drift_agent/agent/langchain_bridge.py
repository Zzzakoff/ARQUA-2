from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from drift_agent.agent.tools import call_tool
from drift_agent.context_tools import ContextToolkit

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import StructuredTool

    try:
        from pydantic import create_model
    except Exception:  # pragma: no cover - optional dependency edge
        create_model = None

    LANGCHAIN_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path when langchain is absent
    AIMessage = HumanMessage = SystemMessage = ToolMessage = None
    StructuredTool = None
    create_model = None
    LANGCHAIN_AVAILABLE = False


@dataclass
class SimpleMessage:
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    name: str | None = None


@dataclass
class SimpleTool:
    name: str
    description: str
    func: Callable[[dict[str, Any]], dict[str, Any]]

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.func(arguments)


def system_message(content: str) -> Any:
    if LANGCHAIN_AVAILABLE:
        return SystemMessage(content=content)
    return SimpleMessage(role="system", content=content)


def human_message(content: str) -> Any:
    if LANGCHAIN_AVAILABLE:
        return HumanMessage(content=content)
    return SimpleMessage(role="user", content=content)


def ai_message(content: str, tool_calls: list[dict[str, Any]] | None = None) -> Any:
    if LANGCHAIN_AVAILABLE:
        kwargs = {"content": content}
        if tool_calls:
            kwargs["additional_kwargs"] = {"tool_calls": tool_calls}
        return AIMessage(**kwargs)
    return SimpleMessage(role="assistant", content=content, tool_calls=tool_calls)


def tool_message(content: str, name: str) -> Any:
    if LANGCHAIN_AVAILABLE:
        return ToolMessage(content=content, name=name, tool_call_id=name)
    return SimpleMessage(role="tool", content=content, name=name)


def messages_for_provider(messages: list[Any]) -> list[dict[str, Any]]:
    provider_messages: list[dict[str, Any]] = []
    for message in messages:
        if LANGCHAIN_AVAILABLE:
            if message.__class__.__name__ == "SystemMessage":
                payload = {"role": "system", "content": _stringify_content(message.content)}
            elif message.__class__.__name__ == "HumanMessage":
                payload = {"role": "user", "content": _stringify_content(message.content)}
            elif message.__class__.__name__ == "AIMessage":
                payload = {"role": "assistant", "content": _stringify_content(message.content)}
                tool_calls = getattr(message, "additional_kwargs", {}).get("tool_calls")
                if tool_calls:
                    payload["tool_calls"] = tool_calls
            elif message.__class__.__name__ == "ToolMessage":
                payload = {"role": "tool", "content": _stringify_content(message.content), "name": getattr(message, "name", None)}
            else:
                payload = {"role": "user", "content": _stringify_content(getattr(message, "content", ""))}
        else:
            payload = {"role": message.role, "content": message.content}
            if message.tool_calls:
                payload["tool_calls"] = message.tool_calls
            if message.name:
                payload["name"] = message.name
        provider_messages.append(payload)
    return provider_messages


def build_tools(toolkit: ContextToolkit, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for spec in tool_specs:
        function = spec["function"]
        name = function["name"]
        description = function["description"]
        tool_func = _make_tool_func(toolkit, name)
        if LANGCHAIN_AVAILABLE and StructuredTool is not None and create_model is not None:
            schema_model = _build_args_model(name, function.get("parameters", {}))
            tools[name] = StructuredTool.from_function(
                func=tool_func,
                name=name,
                description=description,
                args_schema=schema_model,
            )
        else:
            tools[name] = SimpleTool(name=name, description=description, func=lambda arguments, f=tool_func: f(**arguments))
    return tools


def _make_tool_func(toolkit: ContextToolkit, name: str) -> Callable[..., dict[str, Any]]:
    def run_tool(**kwargs: Any) -> dict[str, Any]:
        return call_tool(toolkit, name, kwargs)

    return run_tool


def _build_args_model(name: str, schema: dict[str, Any]) -> type[Any]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, tuple[type[Any], Any]] = {}
    for prop_name in properties:
        annotation = Any
        default = ... if prop_name in required else None
        fields[prop_name] = (annotation, default)
    return create_model(f"{name.title()}Args", **fields)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_stringify_content(item) for item in content)
    return str(content)
