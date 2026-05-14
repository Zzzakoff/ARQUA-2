# api-drift-agent

`api-drift-agent` detects drift between an OpenAPI 3.x contract and a FastAPI codebase.

![](/assets/first.gif)



It is built around two layers:

- a deterministic analyzer that parses the OpenAPI document, statically walks the FastAPI source tree, and reports exact contract differences
- an explanation layer built around a LangChain agent loop that asks an LLM whether the spec or code should be treated as the source of truth and proposes patch artifacts

The tool is useful when a FastAPI app and its published OpenAPI contract start evolving separately. It highlights missing endpoints, extra endpoints, schema mismatches, status-code differences, undocumented fields, required/nullability drift, and parameter drift.

## Highlights

- OpenAPI YAML/JSON parsing for OpenAPI 3.x contracts
- Static FastAPI route analysis across single-file and router-based apps
- Pydantic model extraction for request and response schemas
- Deterministic drift classification with stable IDs
- Interactive Rich TUI for local inspection
- JSON output for CI and automation
- LangChain-based explanation and tool orchestration
- Optional explain mode with either Ollama or Groq
- Patch preview artifacts for spec and code-review workflows
- Config-file defaults via `.drift-check.yml`
- Ignore rules for known or intentional drift
- Test fixtures for realistic FastAPI/OpenAPI drift cases

## Installation

Use Python 3.11 or newer.

```bash
pip install api-drift-agent
```

The CLI entrypoint is:

```bash
drift-check
```

The explanation layer also uses:

```text
langchain-core
```

LangChain powers the explanation agent, message flow, and tool orchestration. The spec parser, FastAPI analyzer, and diff engine remain deterministic by design.

## Quick Start

Run the deterministic drift check:

```bash
drift-check --spec openapi.yaml --src ./app
```

Run against the included drift lab fixture:

```bash
drift-check --spec tests/fixtures/specs/drift_lab.yaml --src tests/fixtures/apps/drift_lab_app
```

If you omit `--spec` or `--src`, the interactive TUI prompts for the missing paths:

```bash
drift-check
```

Emit JSON for CI:

```bash
drift-check --spec openapi.yaml --src ./app --output-format json --output-file drift-report.json
```

Fail the command when error-severity drift exists:

```bash
drift-check --spec openapi.yaml --src ./app --output-format json --exit-code
```
## Video Demo

https://github.com/user-attachments/assets/755ae9f6-fec0-4c4d-94cd-be6ab2d69c8f

## What The Tool Detects

`api-drift-agent` compares normalized endpoint contracts from the spec and code.

It can report:

- `missing_endpoint`: endpoint exists in the OpenAPI spec but not in FastAPI code
- `ghost_endpoint`: endpoint exists in code but not in the OpenAPI spec
- `additive_drift`: code accepts or returns fields not documented in the spec
- `destructive_drift`: spec documents fields or schemas missing from code
- `type_drift`: schema type, format, or enum values differ
- `nullability_drift`: nullable behavior differs
- `required_drift`: required flags differ
- `status_code_drift`: documented and implemented status codes differ
- `parameter_drift`: path/query/header/cookie parameters differ

Each drift item includes:

- stable drift ID
- endpoint
- category
- location
- detail
- spec evidence
- code evidence
- severity: `error`, `warning`, or `info`

## Interactive TUI

By default, non-JSON output opens a Rich TUI-style view.

The TUI includes:

- header with current phase
- run summary panel
- agent explanation panel
- deterministic drift panel
- footer with severity totals and scroll controls

![](/assets/image.png)
The deterministic drift appears as soon as the static comparison is complete. If explain mode is enabled, the agent runs after that while the deterministic output remains visible.

### TUI Controls

After the scan completes, the TUI remains open in an interactive terminal.

Deterministic drift panel:

- `j` or Down: scroll down
- `k` or Up: scroll up
- PageDown or Space: page down
- PageUp: page up
- Home: jump to top
- End: jump to bottom

Explainability panel:

- `z`: scroll explanation findings down
- `a`: scroll explanation findings up
- `x`: page explanation findings down
- `s`: page explanation findings up

Exit:

- `q`
- Esc
- Enter

The panels show visual cues such as `top`, `bottom`, `up more`, `down more`, and current scroll position.

## Explain Mode

Explain mode asks an LLM to inspect each drift item and produce an `AgentFinding`.

The explain layer uses a LangChain agent architecture built around:

- LangChain system/user/assistant/tool messages
- LangChain structured tools wrapping the existing context toolkit
- provider-specific conversion before sending requests to Ollama or Groq

This gives the project a deterministic contract-analysis core with an agent-oriented reasoning layer on top.

An agent finding contains:

- source of truth: `CODE`, `SPEC`, or `AMBIGUOUS`
- confidence: `high`, `medium`, or `low`
- reasoning
- optional patch recommendation

The explainability panel shows:

- source-of-truth decision
- endpoint
- confidence
- reasoning
- drift category and location
- patch target/type/location when available
- patch content preview when available
- `manual review / no automatic codefix` when no safe patch is available

### LangChain In The Project

LangChain is used for the reasoning layer:

- tool-driven drift investigation
- structured message flow
- source-of-truth decisions
- provider-flexible explanation generation

The project keeps the following layers deterministic:

- OpenAPI parsing
- FastAPI codebase analysis
- drift comparison

That split keeps contract detection exact and testable while making explainability and patch recommendation agent-driven.

### Ollama Explain Provider

Ollama is the default explain provider.

Install and run Ollama, then pull the default model:

```bash
ollama pull qwen2.5-coder:7b
```

Run explain mode:

```bash
drift-check --spec openapi.yaml --src ./app --explain
```

Use a different Ollama model:

```bash
drift-check --spec openapi.yaml --src ./app --explain --model qwen2.5-coder:14b
```

### Groq Explain Provider

Groq is supported through its OpenAI-compatible chat completions API.

Set an API key in the environment:

```bash
export GROQ_KEY=your-key
```

or in `.env`:

```env
GROQ_KEY=your-key
```

The tool also accepts `GROQ_API_KEY`. `GROK_KEY` is accepted as a backwards-compatible alias from an earlier typo.

Run Groq explain mode:

```bash
drift-check --spec openapi.yaml --src ./app --explain --explain-provider groq
```

Use another Groq model:

```bash
drift-check --spec openapi.yaml --src ./app --explain --explain-provider groq --groq-model llama-3.1-8b-instant
```

Default Groq model:

```text
llama-3.3-70b-versatile
```

When `GROQ_KEY` or `GROQ_API_KEY` is present and you run the interactive TUI, the CLI asks whether to enable explain mode and whether to use Ollama or Groq.

## Patch Generation

Patch artifacts are generated only when explain mode is enabled and `--patch-dir` is set.

Example:

```bash
drift-check --spec openapi.yaml --src ./app --explain --patch-dir patches --patch-mode preview
```

Patch outputs can include:

- `spec_patched.yaml`: preview of the OpenAPI spec after applying safe spec patches
- `code_patch_summary.md`: summary of code patch suggestions
- `ambiguous.md`: drift items that require manual review
- `backups/`: original files when code patches are applied

Patch modes:

- `preview`: write patch artifacts without modifying code
- `apply`: apply eligible code patches after safety checks

Code patch application is conservative:

- target file must exist
- file must not have uncommitted changes
- generated Python must parse successfully
- backup is written before modification

Spec patch application is also defensive:

- OpenAPI path keys such as `/api/users/{user_id}` are handled as literal path keys
- list indexes such as `parameters/0/schema/type` are supported
- malformed model-generated patch locations are recorded as patch errors instead of crashing the run

## JSON Output

Use JSON output for automation:

```bash
drift-check --spec openapi.yaml --src ./app --output-format json
```

The JSON payload contains:

- run ID
- timestamp
- spec path
- source path
- spec endpoint count
- code endpoint count
- drift items
- severity summary
- optional agent findings
- optional patch report

Example shape:

```json
{
  "run_id": "abc12345",
  "timestamp": "2026-04-23T12:00:00+00:00",
  "spec_path": "openapi.yaml",
  "src_path": "./app",
  "spec_endpoints": 12,
  "code_endpoints": 13,
  "items": [],
  "summary": {
    "error": 0,
    "warning": 0,
    "info": 0,
    "total": 0
  }
}
```

Write JSON to a file:

```bash
drift-check --spec openapi.yaml --src ./app --output-format json --output-file drift-report.json
```

## Configuration

You can define defaults in `.drift-check.yml` in the current working directory.

```yaml
spec: openapi.yaml
src: ./app
patch_dir: ./patches
explain_provider: groq
ignore:
  - endpoint: "GET /health"
    category: "ghost_endpoint"
```

CLI flags override config values.

### Ignore Rules

Ignore rules let you suppress known or intentional drift.

Each rule can match:

- endpoint pattern
- drift category

Endpoint patterns use shell-style matching through `fnmatch`.

Example:

```yaml
ignore:
  - endpoint: "GET /health"
    category: "ghost_endpoint"
  - endpoint: "GET /internal/*"
```

## Environment Variables

Supported environment variables:

- `GROQ_KEY`: Groq API key
- `GROQ_API_KEY`: Groq API key using Groq's documented naming convention
- `GROK_KEY`: accepted as a legacy alias

The CLI also reads these values from `.env` in the current working directory.

## CLI Reference

```text
--spec PATH
```

Path to the OpenAPI YAML or JSON file.

```text
--src PATH
```

Path to the FastAPI project root or source directory.

```text
--explain
```

Enable the LLM-backed explanation layer.

```text
--explain-provider ollama|groq
```

Choose the explain provider. Defaults to `ollama`.

```text
--model MODEL
```

Ollama model name. Defaults to `qwen2.5-coder:7b`.

```text
--groq-model MODEL
```

Groq model name. Defaults to `llama-3.3-70b-versatile`.

```text
--patch-dir PATH
```

Directory for patch artifacts. Defaults to `patches` through the CLI flow.

```text
--patch-mode preview|apply
```

Patch behavior. Defaults to `preview`.

```text
--output-format rich|json
```

Output format. Defaults to `rich`, which uses the TUI.

```text
--output-file PATH
```

Write the JSON payload to a file. This can be used with either output format.

```text
--exit-code
```

Exit with code `1` when error-severity drift exists.

## Project Architecture

```text
src/drift_agent/
  agent/
    core.py          # Ollama/Groq agent orchestration and response parsing
    langchain_bridge.py  # LangChain message and tool adapter layer
    prompts.py       # system prompt and tool schema
    tools.py         # context tool dispatch used by the agent layer
  code_analyzer/
    walker.py        # source tree discovery
    extractor.py     # FastAPI route/model extraction
    resolver.py      # type/schema resolution helpers
  context_tools/
    coverage.py      # coverage lookup helper
    git.py           # git context helper
    search.py        # source search helper
    toolkit.py       # tool container used by agent
  diff_engine/
    classifier.py    # stable drift IDs
    comparator.py    # deterministic contract comparison
  patch_generator/
    code_patch.py    # code patch application
    spec_patch.py    # OpenAPI patch application
    generator.py     # patch report orchestration
  spec_parser/
    parser.py        # OpenAPI parsing
    resolver.py      # schema/ref resolution
  cli.py             # Typer CLI and Rich TUI
  types.py           # shared dataclasses
  errors.py          # project error types
```

## Test Fixtures

The repository includes fixtures under `tests/fixtures/`.

Important fixtures:

- `tests/fixtures/specs/drift_lab.yaml`
- `tests/fixtures/apps/drift_lab_app`
- `tests/fixtures/specs/simple.yaml`
- `tests/fixtures/apps/simple_app`
- `tests/fixtures/specs/with_refs.yaml`
- `tests/fixtures/specs/circular_refs.yaml`

There is also a larger standalone fixture under `test/`:

- `test/fastapi_app.py`
- `test/openapi.yaml`

That fixture is useful for manually testing broader FastAPI and OpenAPI behavior.

## Development

Run all tests:

```bash
python -m pytest -q
```

Compile-check key files:

```bash
python -m py_compile src/drift_agent/cli.py src/drift_agent/agent/core.py
```

Run the fixture drift check:

```bash
drift-check --spec tests/fixtures/specs/drift_lab.yaml --src tests/fixtures/apps/drift_lab_app
```

Run fixture drift check with JSON output:

```bash
drift-check --spec tests/fixtures/specs/drift_lab.yaml --src tests/fixtures/apps/drift_lab_app --output-format json
```

## GitHub Actions

The repository includes a workflow at:

```text
.github/workflows/drift-check.yml
```

Use JSON output and `--exit-code` for CI-style enforcement.

## Limitations

- Static FastAPI analysis is best-effort and focuses on common FastAPI/Pydantic patterns.
- Highly dynamic route registration may not be detected.
- Explain mode depends on the selected model and can be slow on large drift reports.
- LLM-produced patches are treated defensively and may be marked ambiguous.
- Groq explain mode requires network access and a valid API key.
- Ollama explain mode requires a local Ollama runtime and the selected model.

## Typical Workflows

### Local Contract Review

```bash
drift-check --spec openapi.yaml --src ./app
```

Use the TUI to inspect drift, then decide whether to update code or spec.

### Explain And Patch Preview

```bash
drift-check --spec openapi.yaml --src ./app --explain --patch-dir patches --patch-mode preview
```

Review:

- `patches/spec_patched.yaml`
- `patches/code_patch_summary.md`
- `patches/ambiguous.md`

### CI Drift Gate

```bash
drift-check --spec openapi.yaml --src ./app --output-format json --output-file drift-report.json --exit-code
```

The command exits with `1` if error-severity drift exists.

## Status

Implementation progress is summarized in `WORK_DONE.md`.
