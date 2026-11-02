from drift_agent.agent.core import DriftAgent, GroqChatClient
from drift_agent.agent.langchain_bridge import ai_message, build_tools, human_message, messages_for_provider, system_message, tool_message
from drift_agent.cli import _finding_explanation, _load_env_file
from drift_agent.context_tools import ContextToolkit
from drift_agent.types import DriftCategory, DriftItem


class FakeClient:
    def show(self, model):
        return {"name": model}

    def chat(self, **kwargs):
        return {"message": {"content": "{\"drift_item_id\": \"abc123\", \"source_of_truth\": \"CODE\", \"confidence\": \"high\", \"reasoning\": \"Looks intentional.\", \"tools_called\": [], \"patch\": {\"target\": \"spec\", \"patch_type\": \"add_field\", \"location\": \"components/schemas/UserResponse/properties\", \"content\": \"created_at:\\n  type: string\"}}"}}


class BadJsonClient:
    def show(self, model):
        return {"name": model}

    def chat(self, **kwargs):
        return {"message": {"content": "I cannot produce JSON for this item."}}


def test_agent_fast_path(monkeypatch, tmp_path):
    monkeypatch.setattr("drift_agent.agent.core.ollama.Client", lambda host: FakeClient())
    toolkit = ContextToolkit(project_root=tmp_path, spec_path=tmp_path / "openapi.yaml")
    agent = DriftAgent(toolkit=toolkit)
    finding = agent.analyze(
        [
            DriftItem(
                id="1",
                endpoint="GET /users",
                category=DriftCategory.STATUS_CODE_DRIFT,
                location="response.204",
                detail="Extra code status",
                spec_evidence=None,
                code_evidence="204",
                severity="info",
            )
        ]
    )[0]

    assert finding.source_of_truth == "AMBIGUOUS"
    assert finding.patch is None


def test_agent_extracts_json_from_fenced_response():
    agent = DriftAgent.__new__(DriftAgent)

    payload = agent._parse_json_object(
        """
        Here is the result:
        ```json
        {"source_of_truth": "CODE", "confidence": "high", "reasoning": "ok", "patch": null}
        ```
        """
    )

    assert payload["source_of_truth"] == "CODE"


def test_agent_parses_yaml_like_object_response():
    agent = DriftAgent.__new__(DriftAgent)

    payload = agent._parse_json_object(
        """
        source_of_truth: CODE
        confidence: high
        reasoning: ok
        patch:
          target: spec
          patch_type: change_type
          location: paths//api/orders/get/parameters/0/schema/type
          content: integer
        """
    )

    assert payload["patch"]["content"] == "integer"


def test_agent_marks_malformed_model_response_ambiguous(monkeypatch, tmp_path):
    monkeypatch.setattr("drift_agent.agent.core.ollama.Client", lambda host: BadJsonClient())
    toolkit = ContextToolkit(project_root=tmp_path, spec_path=tmp_path / "openapi.yaml")
    agent = DriftAgent(toolkit=toolkit)

    finding = agent.analyze(
        [
            DriftItem(
                id="1",
                endpoint="GET /users",
                category=DriftCategory.ADDITIVE_DRIFT,
                location="response.200.schema.name",
                detail="Missing field",
                spec_evidence=None,
                code_evidence="string",
                severity="warning",
            )
        ]
    )[0]

    assert finding.source_of_truth == "AMBIGUOUS"
    assert finding.patch is None


def test_agent_progress_callback_receives_findings(monkeypatch, tmp_path):
    monkeypatch.setattr("drift_agent.agent.core.ollama.Client", lambda host: FakeClient())
    toolkit = ContextToolkit(project_root=tmp_path, spec_path=tmp_path / "openapi.yaml")
    agent = DriftAgent(toolkit=toolkit)
    progress = []

    findings = agent.analyze(
        [
            DriftItem(
                id="1",
                endpoint="GET /users",
                category=DriftCategory.ADDITIVE_DRIFT,
                location="response.200.schema.created_at",
                detail="Missing field",
                spec_evidence=None,
                code_evidence="string/date-time",
                severity="warning",
            )
        ],
        on_finding=lambda finding, index, total: progress.append((finding.source_of_truth, index, total)),
    )

    assert findings[0].source_of_truth == "CODE"
    assert progress == [("CODE", 1, 1)]


def test_groq_client_sanitizes_messages_for_api():
    client = GroqChatClient(api_key="test")

    messages = client._messages_for_api(
        [
            {"role": "system", "content": "system"},
            {"role": "tool", "name": "search", "content": {"ok": True}},
            {"role": "unexpected", "content": "fallback"},
        ]
    )

    assert messages == [
        {"role": "system", "content": "system"},
        {"role": "tool", "content": "{'ok': True}"},
        {"role": "user", "content": "fallback"},
    ]


def test_load_env_file_reads_groq_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# ignored",
                "GROQ_KEY='secret-key'",
                "OTHER=value",
            ]
        ),
        encoding="utf-8",
    )

    values = _load_env_file(env_path)

    assert values["GROQ_KEY"] == "secret-key"
    assert values["OTHER"] == "value"


def test_finding_explanation_includes_patch_details():
    finding = DriftAgent.__new__(DriftAgent)._finding_from_payload(
        DriftItem(
            id="1",
            endpoint="GET /users",
            category=DriftCategory.ADDITIVE_DRIFT,
            location="response.200.schema.created_at",
            detail="Missing field",
            spec_evidence=None,
            code_evidence="string/date-time",
            severity="warning",
        ),
        {
            "source_of_truth": "CODE",
            "confidence": "high",
            "reasoning": "Code returns this field consistently.",
            "patch": {
                "target": "spec",
                "patch_type": "add_field",
                "location": "paths//users/get/responses/200/content/application/json/schema/properties",
                "content": "created_at:\n  type: string\n  format: date-time",
            },
        },
        [],
    )

    explanation = _finding_explanation(finding)

    assert "Code returns this field consistently." in explanation
    assert "patch: spec add_field" in explanation
    assert "created_at" in explanation


def test_langchain_bridge_messages_fallback_shape():
    messages = messages_for_provider(
        [
            system_message("system"),
            human_message("user"),
            ai_message("assistant"),
            tool_message('{"ok": true}', "search_codebase"),
        ]
    )

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "tool"


def test_langchain_bridge_build_tools_invokes_context_tool():
    class DummyToolkit:
        def call_tool(self, name, arguments):
            return {"name": name, "arguments": arguments}

    tools = build_tools(
        DummyToolkit(),
        [
            {
                "function": {
                    "name": "search_codebase",
                    "description": "Search",
                    "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                }
            }
        ],
    )

    result = tools["search_codebase"].invoke({"pattern": "TODO"})

    assert result["name"] == "search_codebase"
    assert result["arguments"] == {"pattern": "TODO"}

