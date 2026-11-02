from __future__ import annotations

import json
import textwrap
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any, Callable

import ollama
import yaml

from drift_agent.agent.langchain_bridge import ai_message, build_tools, human_message, messages_for_provider, system_message, tool_message
from drift_agent.agent.prompts import SYSTEM_PROMPT, TOOLS
from drift_agent.context_tools import ContextToolkit
from drift_agent.errors import AgentFailure, ModelNotAvailableError, OllamaConnectionError
from drift_agent.types import AgentFinding, DriftCategory, DriftItem, PatchSpec


class GroqChatClient:
    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1", timeout: int = 3600):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def show(self, model: str) -> dict[str, str]:
        return {"name": model}

    def chat(self, *, model: str, messages: list[dict[str, Any]], options: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": self._messages_for_api(messages),
            "temperature": (options or {}).get("temperature", 0.1),
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentFailure(f"Groq request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise AgentFailure(f"Groq request failed: {exc.reason}") from exc
        return {"message": data.get("choices", [{}])[0].get("message", {})}

    def _messages_for_api(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        api_messages: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role", "user")
            if role not in {"system", "user", "assistant", "tool"}:
                role = "user"
            api_messages.append({"role": role, "content": str(message.get("content", ""))})
        return api_messages


class DriftAgent:
    def __init__(
        self,
        toolkit: ContextToolkit,
        model: str = "qwen2.5-coder:7b",
        ollama_host: str = "http://localhost:11434",
        provider: str = "ollama",
        groq_api_key: str | None = None,
        groq_base_url: str = "https://api.groq.com/openai/v1",
    ):
        self.toolkit = toolkit
        self.model = model
        self.provider = provider
        if provider == "groq":
            if not groq_api_key:
                raise AgentFailure("GROQ_KEY is required when explain provider is groq")
            self.client = GroqChatClient(api_key=groq_api_key, base_url=groq_base_url)
        else:
            self.client = ollama.Client(host=ollama_host)
        self.langchain_tools = build_tools(toolkit, TOOLS)
        self._check_model()

    def analyze(self, drift_items: list[DriftItem], on_finding: Callable[[AgentFinding, int, int], None] | None = None) -> list[AgentFinding]:
        findings: list[AgentFinding] = []
        total = len(drift_items)
        for index, item in enumerate(drift_items, start=1):
            finding = self._analyze_item(item)
            findings.append(finding)
            if on_finding:
                on_finding(finding, index, total)
        return findings

    def _check_model(self) -> None:
        try:
            self.client.show(self.model)
        except ollama.ResponseError as exc:
            raise ModelNotAvailableError(f"{self.model} not found. Run: ollama pull {self.model}") from exc
        except Exception as exc:
            raise OllamaConnectionError("Could not connect to Ollama. Ensure it is running locally.") from exc

    def _analyze_item(self, drift_item: DriftItem) -> AgentFinding:
        if drift_item.requires_review or drift_item.category == DriftCategory.ANALYSIS_LIMITATION:
            return self._ambiguous_finding(drift_item, [], drift_item.detail)
        fast_path = self._fast_path(drift_item)
        if fast_path is not None:
            return fast_path
        messages: list[Any] = [
            system_message(SYSTEM_PROMPT),
            human_message(
                json.dumps(
                    {
                        "drift_item": drift_item.to_dict(),
                        "guidance": "Investigate with tools only if necessary and return the required JSON object.",
                    }
                )
            ),
        ]
        tools_called: list[str] = []
        for _ in range(6):
            response = self.client.chat(
                model=self.model,
                messages=messages_for_provider(messages),
                tools=TOOLS,
                options={"temperature": 0.1},
            )
            message = self._response_message(response)
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                if len(tools_called) >= 5:
                    break
                messages.append(ai_message(message.get("content", ""), tool_calls=tool_calls))
                for tool_call in tool_calls:
                    function_data = tool_call.get("function", {})
                    tool_name = function_data.get("name")
                    if tool_name is None:
                        continue
                    arguments = function_data.get("arguments") or {}
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments or "{}")
                    tools_called.append(tool_name)
                    result = self.langchain_tools[tool_name].invoke(arguments)
                    messages.append(tool_message(json.dumps(result), tool_name))
                continue
            try:
                payload = self._parse_json_with_retry(messages, message.get("content", ""))
            except AgentFailure as exc:
                return self._ambiguous_finding(drift_item, tools_called, str(exc))
            return self._finding_from_payload(drift_item, payload, tools_called)
        return AgentFinding(
            drift_item=drift_item,
            source_of_truth="AMBIGUOUS",
            confidence="low",
            reasoning=f"{drift_item.category.value} at {drift_item.location}. Tool-call budget was exhausted before a reliable conclusion was reached.",
            evidence=[],
            patch=None,
        )

    def _ambiguous_finding(self, drift_item: DriftItem, tools_called: list[str], reason: str) -> AgentFinding:
        return AgentFinding(
            drift_item=drift_item,
            source_of_truth="AMBIGUOUS",
            confidence="low",
            reasoning=f"{drift_item.category.value} at {drift_item.location}. {reason}",
            evidence=[{"tools_called": tools_called}],
            patch=None,
        )

    def _parse_json_with_retry(self, messages: list[Any], content: str) -> dict[str, Any]:
        try:
            return self._parse_json_object(content)
        except json.JSONDecodeError:
            messages.extend(
                [
                    ai_message(content),
                    human_message("Your previous response was not valid JSON. Return only the required JSON object."),
                ]
            )
            retry = self.client.chat(
                model=self.model,
                messages=messages_for_provider(messages),
                tools=TOOLS,
                options={"temperature": 0.1},
            )
            retry_content = self._response_message(retry).get("content", "")
            try:
                return self._parse_json_object(retry_content)
            except json.JSONDecodeError as exc:
                raise AgentFailure("Agent returned malformed JSON twice") from exc

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        stripped = textwrap.dedent(content).strip()
        candidates = [stripped]
        if "```" in stripped:
            candidates.extend(part.strip() for part in stripped.split("```") if part.strip())
            candidates.extend(part.removeprefix("json").strip() for part in stripped.split("```") if part.strip().startswith("json"))
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    payload, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
            try:
                payload = yaml.safe_load(candidate)
            except yaml.YAMLError:
                continue
            if isinstance(payload, dict):
                return payload
        raise json.JSONDecodeError("No JSON object found", content, 0)

    def _finding_from_payload(self, drift_item: DriftItem, payload: dict[str, Any], tools_called: list[str]) -> AgentFinding:
        patch_data = payload.get("patch")
        patch = None
        if patch_data:
            patch = PatchSpec(
                target=patch_data["target"],
                patch_type=patch_data["patch_type"],
                location=patch_data["location"],
                content=patch_data["content"],
            )
        return AgentFinding(
            drift_item=drift_item,
            source_of_truth=payload["source_of_truth"],
            confidence=payload["confidence"],
            reasoning=payload["reasoning"],
            evidence=[{"tools_called": tools_called}],
            patch=patch,
        )

    def _fast_path(self, drift_item: DriftItem) -> AgentFinding | None:
        if drift_item.category == DriftCategory.STATUS_CODE_DRIFT and drift_item.severity == "info":
            return AgentFinding(
                drift_item=drift_item,
                source_of_truth="AMBIGUOUS",
                confidence="low",
                reasoning=f"STATUS_CODE_DRIFT at {drift_item.location}. Extra response codes are informational in this workflow, so no automatic patch is generated.",
                evidence=[],
                patch=None,
            )
        if drift_item.category == DriftCategory.NULLABILITY_DRIFT and drift_item.spec_evidence == "True" and drift_item.code_evidence == "False":
            return AgentFinding(
                drift_item=drift_item,
                source_of_truth="CODE",
                confidence="medium",
                reasoning=f"NULLABILITY_DRIFT at {drift_item.location}. Code is stricter than the spec, which is generally safe, so the spec should be tightened to match code.",
                evidence=[],
                patch=self._default_patch(drift_item, target="spec"),
            )
        if drift_item.category == DriftCategory.TYPE_DRIFT and drift_item.spec_evidence == "number" and drift_item.code_evidence == "integer":
            return AgentFinding(
                drift_item=drift_item,
                source_of_truth="CODE",
                confidence="high",
                reasoning=f"TYPE_DRIFT at {drift_item.location}. Integer is a valid subtype of number, so the code is more specific and the spec should be narrowed.",
                evidence=[],
                patch=self._default_patch(drift_item, target="spec"),
            )
        return None

    def _default_patch(self, drift_item: DriftItem, target: str) -> PatchSpec:
        patch_type = "change_type" if drift_item.category == DriftCategory.TYPE_DRIFT else "change_schema"
        location = drift_item.location.replace(".", "/")
        content = drift_item.code_evidence or drift_item.spec_evidence or drift_item.detail
        return PatchSpec(target=target, patch_type=patch_type, location=location, content=content)

    def _response_message(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response.get("message", {})
        if hasattr(response, "message"):
            message = response.message
            if isinstance(message, dict):
                return message
            return {
                "content": getattr(message, "content", ""),
                "tool_calls": getattr(message, "tool_calls", None),
            }
        return {}
