from __future__ import annotations

import json
import os
import sys
import time
import uuid
import textwrap
from collections import Counter
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import typer
import yaml
from rich import box
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from drift_agent.agent import DriftAgent
from drift_agent.code_analyzer import analyze_codebase
from drift_agent.context_tools import ContextToolkit
from drift_agent.diff_engine import compute_drift
from drift_agent.patch_generator import PatchGenerator
from drift_agent.spec_parser import parse_spec
from drift_agent.types import AgentFinding, DriftItem

app = typer.Typer(help="Detect drift between an OpenAPI contract and a FastAPI codebase.")
console = Console()

ACCENT = "rgb(196,141,145)"
GREEN = "rgb(170,207,142)"
BLUE = "rgb(139,149,206)"
MUTED = "rgb(128,139,128)"
BORDER = "rgb(91,115,94)"
WARN = "rgb(223,197,125)"
ERROR = "rgb(222,116,116)"


@app.command()
def main(
    spec: str | None = typer.Option(None, "--spec"),
    src: str | None = typer.Option(None, "--src"),
    explain: bool = typer.Option(False, "--explain"),
    patch_dir: str | None = typer.Option(None, "--patch-dir"),
    patch_mode: str = typer.Option("preview", "--patch-mode"),
    output_format: str = typer.Option("rich", "--output-format"),
    output_file: str | None = typer.Option(None, "--output-file"),
    exit_code: bool = typer.Option(False, "--exit-code"),
    model: str = typer.Option("qwen2.5-coder:7b", "--model"),
    explain_provider: str = typer.Option("ollama", "--explain-provider"),
    groq_model: str = typer.Option("llama-3.3-70b-versatile", "--groq-model"),
) -> None:
    config = _load_config(Path.cwd() / ".drift-check.yml")
    dotenv = _load_env_file(Path.cwd() / ".env")
    groq_key = (
        os.environ.get("GROQ_KEY")
        or os.environ.get("GROQ_API_KEY")
        or os.environ.get("GROK_KEY")
        or dotenv.get("GROQ_KEY")
        or dotenv.get("GROQ_API_KEY")
        or dotenv.get("GROK_KEY")
    )
    spec = spec or config.get("spec")
    src = src or config.get("src")
    patch_dir = patch_dir or config.get("patch_dir") or "patches"
    explain_provider = str(config.get("explain_provider") or explain_provider).lower()
    if output_format != "json":
        console.clear()
    if not spec or not src:
        spec, src = _prompt_for_missing_paths(spec, src)
    if output_format != "json" and groq_key and _can_prompt_interactively():
        explain, explain_provider = _prompt_for_explain_mode(explain, explain_provider)
    if output_format == "json":
        spec_contract = parse_spec(spec)
        code_contract = analyze_codebase(src)
        drift_items = _apply_ignore_rules(compute_drift(spec_contract, code_contract), config.get("ignore", []))
        findings: list[AgentFinding] = []
        patch_report = None
        if explain and drift_items:
            toolkit = ContextToolkit(project_root=src, spec_path=spec)
            findings = _create_agent(toolkit, explain_provider, model, groq_model, groq_key).analyze(drift_items)
            if patch_dir:
                patch_report = PatchGenerator(spec_path=spec, project_root=src, output_dir=patch_dir, patch_mode=patch_mode).generate(findings)
        payload = _build_output(spec, src, spec_contract, code_contract, drift_items, findings, patch_report)
        _emit_output(payload, output_format=output_format, output_file=output_file)
        if exit_code and payload["summary"]["error"] > 0:
            raise typer.Exit(code=1)
        return

    findings: list[AgentFinding] = []
    patch_report = None
    drift_items: list[DriftItem] = []
    spec_contract = None
    code_contract = None
    status_text = "booting deterministic scanner"
    agent_progress = ""
    agent_offset = 0
    use_alt_screen = _can_scroll_interactively()

    with Live(
        _render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=agent_offset),
        console=console,
        refresh_per_second=8,
        auto_refresh=False,
        screen=use_alt_screen,
        vertical_overflow="crop",
    ) as live:
        status_text = "loading OpenAPI contract"
        live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=agent_offset), refresh=True)
        spec_contract = parse_spec(spec)

        status_text = "walking FastAPI source"
        live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=agent_offset), refresh=True)
        code_contract = analyze_codebase(src)

        status_text = "comparing deterministic contract"
        drift_items = _apply_ignore_rules(compute_drift(spec_contract, code_contract), config.get("ignore", []))
        live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=agent_offset), refresh=True)

        if explain and drift_items:
            status_text = f"agent running ({explain_provider})"
            toolkit = ContextToolkit(project_root=src, spec_path=spec)

            def update_agent_progress(finding: AgentFinding, index: int, total: int) -> None:
                findings.append(finding)
                nonlocal agent_progress
                agent_progress = f"{index}/{total} explained - {finding.source_of_truth.lower()} - {finding.drift_item.endpoint}"
                live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=max(0, len(findings) - _agent_visible_count())), refresh=True)

            _create_agent(toolkit, explain_provider, model, groq_model, groq_key).analyze(drift_items, on_finding=update_agent_progress)
            status_text = "generating patch preview"
            agent_offset = max(0, len(findings) - _agent_visible_count())
            live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, agent_offset=agent_offset), refresh=True)
            if patch_dir:
                patch_report = PatchGenerator(spec_path=spec, project_root=src, output_dir=patch_dir, patch_mode=patch_mode).generate(findings)

        status_text = "complete"
        payload = _build_output(spec, src, spec_contract, code_contract, drift_items, findings, patch_report)
        live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, payload, agent_offset=agent_offset), refresh=True)

        if _can_scroll_interactively() and drift_items:
            _scroll_tui(live, spec, src, drift_items, findings, patch_report, explain, agent_progress, payload, agent_offset)
    _emit_output(payload, output_format=output_format, output_file=output_file, already_rendered=True)
    if exit_code and payload["summary"]["error"] > 0:
        raise typer.Exit(code=1)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _prompt_for_missing_paths(spec: str | None, src: str | None) -> tuple[str, str]:
    console.print(
        Panel(
            Align.left(
                Text.assemble(
                    ("api drift agent\n", f"bold {ACCENT}"),
                    ("provide missing inputs to start the scan", MUTED),
                )
            ),
            title="[prompt]",
            border_style=BORDER,
            box=box.SQUARE,
            padding=(1, 2),
        )
    )
    if not spec:
        spec = Prompt.ask(f"[{GREEN}]spec path[/]", default="tests/fixtures/specs/drift_lab.yaml")
    if not src:
        src = Prompt.ask(f"[{GREEN}]source path[/]", default="tests/fixtures/apps/drift_lab_app")
    console.clear()
    return spec, src


def _prompt_for_explain_mode(explain: bool, explain_provider: str) -> tuple[bool, str]:
    console.print(
        Panel(
            Text.assemble(
                ("GROQ_KEY found in .env or environment\n", f"bold {GREEN}"),
                ("choose whether to run explain mode and which model backend should explain the drift", MUTED),
            ),
            title="[explain]",
            border_style=BORDER,
            box=box.SQUARE,
            padding=(1, 2),
        )
    )
    if not explain:
        explain = Confirm.ask(f"[{GREEN}]run explain mode[/]", default=False)
    if explain:
        explain_provider = Prompt.ask(f"[{GREEN}]explain provider[/]", choices=["ollama", "groq"], default="groq")
    console.clear()
    return explain, explain_provider


def _create_agent(
    toolkit: ContextToolkit,
    explain_provider: str,
    ollama_model: str,
    groq_model: str,
    groq_key: str | None,
) -> DriftAgent:
    if explain_provider == "groq":
        if not groq_key:
            raise typer.BadParameter("GROQ_KEY or GROQ_API_KEY is required for --explain-provider groq")
        return DriftAgent(toolkit=toolkit, model=groq_model, provider="groq", groq_api_key=groq_key)
    return DriftAgent(toolkit=toolkit, model=ollama_model)


def _apply_ignore_rules(items: list[DriftItem], ignore_rules: list[dict[str, Any]]) -> list[DriftItem]:
    filtered: list[DriftItem] = []
    for item in items:
        ignored = False
        for rule in ignore_rules:
            endpoint_rule = rule.get("endpoint")
            category_rule = rule.get("category")
            taxonomy_rule = rule.get("taxonomy")
            if endpoint_rule and not fnmatch(item.endpoint, endpoint_rule):
                continue
            if category_rule and item.category.value != category_rule:
                continue
            if taxonomy_rule and item.taxonomy.value != taxonomy_rule:
                continue
            ignored = True
            break
        if not ignored:
            filtered.append(item)
    return filtered


def _build_output(
    spec: str,
    src: str,
    spec_contract,
    code_contract,
    drift_items: list[DriftItem],
    findings: list[AgentFinding],
    patch_report,
) -> dict[str, Any]:
    summary = Counter(item.severity for item in drift_items)
    taxonomy_summary = Counter(item.taxonomy.value for item in drift_items)
    priority_summary = Counter(item.priority for item in drift_items)
    payload = {
        "run_id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec_path": spec,
        "src_path": src,
        "spec_endpoints": len(spec_contract.endpoints),
        "code_endpoints": len(code_contract.endpoints),
        "items": [item.to_dict() for item in drift_items],
        "taxonomy_summary": dict(sorted(taxonomy_summary.items())),
        "priority_summary": {priority: priority_summary[priority] for priority in ("P1", "P2", "P3")},
        "summary": {
            "error": summary.get("error", 0),
            "warning": summary.get("warning", 0),
            "info": summary.get("info", 0),
            "total": len(drift_items),
        },
    }
    if findings:
        payload["findings"] = [
            {
                "drift_item_id": finding.drift_item.id,
                "source_of_truth": finding.source_of_truth,
                "confidence": finding.confidence,
                "reasoning": finding.reasoning,
                "patch": finding.patch.to_dict() if finding.patch else None,
            }
            for finding in findings
        ]
    if patch_report:
        payload["patch_report"] = patch_report.to_dict()
    return payload


def _emit_output(payload: dict[str, Any], output_format: str, output_file: str | None, already_rendered: bool = False) -> None:
    if output_format == "json":
        text = json.dumps(payload, indent=2)
        typer.echo(text)
    elif not already_rendered:
        table = Table(title=f"DRIFT REPORT  {payload['spec_path']} <-> {payload['src_path']}")
        table.add_column("Severity")
        table.add_column("Priority / taxonomy")
        table.add_column("Endpoint")
        table.add_column("Location")
        table.add_column("Detail")
        for item in payload["items"]:
            table.add_row(item["severity"].upper(), f"{item['priority']} / {item['taxonomy']}", item["endpoint"], item["location"], item["detail"])
        console.print(table)
        console.print(
            f"{payload['summary']['total']} drift items | "
            f"{payload['summary']['error']} errors | "
            f"{payload['summary']['warning']} warnings | "
            f"{payload['summary']['info']} info"
        )
    if output_file:
        Path(output_file).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _render_tui(
    spec: str,
    src: str,
    status_text: str,
    drift_items: list[DriftItem],
    findings: list[AgentFinding],
    patch_report,
    explain: bool,
    agent_progress: str,
    payload: dict[str, Any] | None = None,
    deterministic_offset: int = 0,
    agent_offset: int = 0,
) -> Layout:
    layout = Layout(name="root")
    layout.split_column(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3))
    layout["body"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=3))
    layout["left"].split_column(Layout(name="run", size=12), Layout(name="agent"))

    layout["header"].update(_header_panel(status_text, explain, bool(findings), payload is not None))
    layout["run"].update(_run_panel(spec, src, drift_items, findings, patch_report))
    layout["agent"].update(_agent_panel(findings, explain, agent_progress, agent_offset))
    layout["right"].update(_deterministic_panel(drift_items, deterministic_offset))
    layout["footer"].update(_footer_panel(payload))
    return layout


def _header_panel(status_text: str, explain: bool, has_findings: bool, done: bool) -> Panel:
    if done:
        phase = "done"
    elif explain and has_findings:
        phase = "agent"
    elif explain:
        phase = "agent pending"
    else:
        phase = "deterministic"
    text = Text()
    text.append(" api-drift ", style=f"bold {ACCENT}")
    text.append("menu ", style=MUTED)
    text.append("run ", style=GREEN)
    text.append("patch ", style=BLUE)
    text.append("* ", style=ACCENT)
    text.append(f"{phase:<15}", style=WARN if phase.startswith("agent") else GREEN)
    text.append(status_text, style="white")
    return Panel(text, border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _run_panel(spec: str, src: str, drift_items: list[DriftItem], findings: list[AgentFinding], patch_report) -> Panel:
    counts = Counter(item.severity for item in drift_items)
    rows = Table.grid(expand=True)
    rows.add_column(style=MUTED, ratio=1)
    rows.add_column(style="white", ratio=3)
    rows.add_row("spec", spec)
    rows.add_row("src", src)
    rows.add_row("drift", f"{len(drift_items)} total")
    rows.add_row("errors", str(counts.get("error", 0)))
    rows.add_row("warnings", str(counts.get("warning", 0)))
    rows.add_row("info", str(counts.get("info", 0)))
    rows.add_row("agent", f"{len(findings)}/{len(drift_items)}")
    if patch_report:
        rows.add_row("patches", f"{patch_report.spec_patches_applied} spec | {patch_report.ambiguous_count} ambiguous")
    return Panel(rows, title="[run]", border_style=BORDER, box=box.SQUARE)


def _agent_panel(findings: list[AgentFinding], explain: bool, agent_progress: str, offset: int = 0) -> Panel:
    if not explain:
        body = Text("explain disabled\nuse --explain to ask the agent for source-of-truth decisions", style=MUTED)
    elif not findings:
        body = Text.assemble(("agent waiting for deterministic output\n", MUTED), ("status ", ACCENT), (agent_progress or "not started", "white"))
    else:
        visible_count = _agent_visible_count()
        max_offset = max(0, len(findings) - visible_count)
        offset = max(0, min(offset, max_offset))
        table = Table(expand=True, box=box.SIMPLE_HEAD, show_lines=True, border_style=BORDER, pad_edge=False)
        table.add_column("#", style=MUTED, width=3, no_wrap=True)
        table.add_column("truth", width=9, no_wrap=True)
        table.add_column("endpoint", ratio=2, overflow="fold")
        table.add_column("why / fix", ratio=5, overflow="fold")
        for index, finding in enumerate(findings[offset : offset + visible_count], start=offset + 1):
            style = GREEN if finding.source_of_truth == "CODE" else WARN if finding.source_of_truth == "SPEC" else MUTED
            table.add_row(str(index), f"[{style}]{finding.source_of_truth.lower()}[/]", finding.drift_item.endpoint, _finding_explanation(finding))
        table.add_row("", "", "", _scroll_hint(offset, max_offset, "a/s up", "z/x down"))
        body = table
    title = f"[agent explain {offset + 1 if findings else 0}-{min(len(findings), offset + _agent_visible_count())} / {len(findings)}]"
    return Panel(body, title=title, subtitle="[a/z scroll findings | q exits]", border_style=BORDER, box=box.SQUARE)


def _finding_explanation(finding: AgentFinding) -> str:
    reasoning = _clamp_text(finding.reasoning, width=46, max_lines=4)
    lines = [
        f"{finding.confidence} confidence",
        f"drift: {finding.drift_item.category.value} at {finding.drift_item.location}",
        f"why: {reasoning}",
    ]
    if finding.patch:
        lines.append(f"patch: {finding.patch.target} {finding.patch.patch_type} -> {finding.patch.location}")
        content = finding.patch.content.strip()
        if content:
            lines.append(f"content: {_clamp_text(content, width=46, max_lines=2)}")
    else:
        lines.append("patch: manual review / no automatic codefix")
    return "\n".join(lines)


def _deterministic_panel(drift_items: list[DriftItem], offset: int = 0) -> Panel:
    visible_count = _visible_drift_count()
    max_offset = max(0, len(drift_items) - _drift_scroll_window())
    offset = max(0, min(offset, max_offset))
    visible_items = drift_items[offset : offset + visible_count]
    table = Table(
        expand=True,
        box=box.SIMPLE_HEAD,
        border_style=BORDER,
        show_lines=False,
        pad_edge=False,
    )
    table.add_column("sev", style="bold", no_wrap=True, width=7)
    table.add_column("endpoint", overflow="fold", ratio=2)
    table.add_column("location", style=MUTED, overflow="fold", ratio=2)
    table.add_column("detail", overflow="fold", ratio=3)
    for item in visible_items:
        severity_style = ERROR if item.severity == "error" else WARN if item.severity == "warning" else BLUE
        table.add_row(f"[{severity_style}]{item.priority}\n{item.severity.upper()}[/]", item.endpoint, item.location,
                      f"{item.taxonomy.value}\n{item.detail}")
    if not drift_items:
        table.add_row(f"[{MUTED}]WAIT[/]", "deterministic scan pending", "", "")
    else:
        table.add_row("", "", "", _scroll_hint(offset, max_offset, "k/pgup up", "j/pgdn down"))
    title = f"[deterministic drift {offset + 1 if drift_items else 0}-{offset + len(visible_items)} / {len(drift_items)}]"
    return Panel(table, title=title, subtitle=_scroll_subtitle(offset, max_offset, "j/k, pgup/pgdn"), border_style=BORDER, box=box.SQUARE)


def _footer_panel(payload: dict[str, Any] | None) -> Panel:
    if not payload:
        text = Text("deterministic output appears on the right as soon as it is ready", style=MUTED)
    else:
        summary = payload["summary"]
        text = Text.assemble(
            (f"{summary['total']} drift items", "white"),
            (" | ", MUTED),
            (f"{summary['error']} errors", ERROR),
            (" | ", MUTED),
            (f"{summary['warning']} warnings", WARN),
            (" | ", MUTED),
            (f"{summary['info']} info", BLUE),
        )
        if "patch_report" in payload:
            text.append(" | patches written", style=GREEN)
        text.append(" | drift: j/k pgup/pgdn | explain: a/z s/x | q exits", style=MUTED)
    return Panel(Align.center(text), border_style=BORDER, box=box.SQUARE)


def _scroll_hint(offset: int, max_offset: int, up_label: str, down_label: str) -> str:
    if max_offset <= 0:
        return f"[{MUTED}]all items visible[/]"
    up = f"↑ more ({up_label})" if offset > 0 else "top"
    down = f"↓ more ({down_label})" if offset < max_offset else "bottom"
    return f"[{ACCENT}]{up}[/]  [{GREEN}]{offset + 1}/{max_offset + 1}[/]  [{ACCENT}]{down}[/]"


def _scroll_subtitle(offset: int, max_offset: int, keys: str) -> str:
    if max_offset <= 0:
        return "[all visible | q exits]"
    markers = []
    markers.append("↑" if offset > 0 else "top")
    markers.append("↓" if offset < max_offset else "bottom")
    return f"[{' '.join(markers)} | {keys} | q exits]"


def _visible_drift_count() -> int:
    return max(6, console.height - 12)


def _drift_scroll_window() -> int:
    return max(3, (console.height - 10) // 3)


def _agent_visible_count() -> int:
    return max(1, (console.height - 18) // 8)


def _clamp_text(value: str, width: int = 48, max_lines: int = 3) -> str:
    wrapped = textwrap.wrap(" ".join(value.split()), width=width) or [""]
    clipped = wrapped[:max_lines]
    if len(wrapped) > max_lines:
        clipped[-1] = clipped[-1][: max(0, width - 3)] + "..."
    return "\n".join(clipped)


def _can_scroll_interactively() -> bool:
    if os.environ.get("CI") is not None:
        return False
    if os.name == "nt":
        return console.is_interactive or sys.stdout.isatty()
    return sys.stdin.isatty() and sys.stdout.isatty()


def _can_prompt_interactively() -> bool:
    return os.environ.get("CI") is None and sys.stdin.isatty()


def _scroll_tui(
    live: Live,
    spec: str,
    src: str,
    drift_items: list[DriftItem],
    findings: list[AgentFinding],
    patch_report,
    explain: bool,
    agent_progress: str,
    payload: dict[str, Any],
    agent_offset: int = 0,
) -> None:
    offset = 0
    agent_offset = max(0, min(agent_offset, max(0, len(findings) - _agent_visible_count())))
    page = _drift_scroll_window()
    max_offset = max(0, len(drift_items) - page)
    agent_page = _agent_visible_count()
    max_agent_offset = max(0, len(findings) - agent_page)
    status_text = "scroll: j/k drift, a/z explanations, q exits"
    live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, payload, offset, agent_offset), refresh=True)
    while True:
        key = _read_key()
        if key in {"q", "esc", "enter"}:
            break
        if key in {"down", "j"}:
            offset += 1
        elif key in {"up", "k"}:
            offset -= 1
        elif key in {"pagedown", "space"}:
            offset += page
        elif key == "pageup":
            offset -= page
        elif key == "home":
            offset = 0
        elif key == "end":
            offset = max_offset
        elif key == "z":
            agent_offset += 1
        elif key == "a":
            agent_offset -= 1
        elif key == "x":
            agent_offset += agent_page
        elif key == "s":
            agent_offset -= agent_page
        offset = max(0, min(offset, max_offset))
        agent_offset = max(0, min(agent_offset, max_agent_offset))
        live.update(_render_tui(spec, src, status_text, drift_items, findings, patch_report, explain, agent_progress, payload, offset, agent_offset), refresh=True)


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        while True:
            if not msvcrt.kbhit():
                time.sleep(0.05)
                continue
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                code = msvcrt.getwch()
                return {
                    "H": "up",
                    "P": "down",
                    "I": "pageup",
                    "Q": "pagedown",
                    "S": "pagedown",
                    "R": "pageup",
                    "G": "home",
                    "O": "end",
                }.get(code, "")
            if char == "\x1b":
                return "esc"
            if char in ("\r", "\n"):
                return "enter"
            if char == " ":
                return "space"
            return char.lower()

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            char = sys.stdin.read(1)
            if char == "\x1b":
                if select.select([sys.stdin], [], [], 0.01)[0]:
                    sequence = sys.stdin.read(2)
                    if sequence in {"[5", "[6"} and select.select([sys.stdin], [], [], 0.01)[0]:
                        sys.stdin.read(1)
                    return {
                        "[A": "up",
                        "[B": "down",
                        "[5": "pageup",
                        "[6": "pagedown",
                        "[H": "home",
                        "[F": "end",
                    }.get(sequence, "esc")
                return "esc"
            if char in ("\r", "\n"):
                return "enter"
            if char == " ":
                return "space"
            return char.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    app()
