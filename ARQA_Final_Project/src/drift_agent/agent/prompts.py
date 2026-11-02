from __future__ import annotations

import json

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Get recent git commit history for a source file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "n": {"type": "integer"},
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log_spec",
            "description": "Get recent git commit history for the active spec file",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_commit_message",
            "description": "Get the full commit message and diff stats for a commit",
            "parameters": {
                "type": "object",
                "properties": {
                    "hash": {"type": "string"},
                },
                "required": ["hash"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_test_coverage",
            "description": "Get test coverage for an endpoint or source file",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string"},
                    "source_file": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": "Search the codebase for a literal string",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "file_glob": {"type": "string"},
                    "context_lines": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_slice",
            "description": "Read a slice of a file with line numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["filepath", "start_line"],
            },
        },
    },
]

SYSTEM_PROMPT = "\n".join(
    [
        "You are a static analysis agent for API contract drift investigation.",
        "Use tools only when needed, never exceed five tool calls per drift item, and always return valid JSON.",
        "If a drift item is low confidence or conflicting, mark it AMBIGUOUS and return patch=null.",
        "The output schema is:",
        json.dumps(
            {
                "drift_item_id": "string",
                "source_of_truth": "CODE | SPEC | AMBIGUOUS",
                "confidence": "high | medium | low",
                "reasoning": "single paragraph",
                "tools_called": ["tool_name"],
                "patch": {
                    "target": "spec | code",
                    "patch_type": "string",
                    "location": "string",
                    "content": "string",
                },
            },
            indent=2,
        ),
    ]
)

