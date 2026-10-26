'''
Запускается анализатор, сохраняются отчёты и определяется результат проверки
Коды: 0 - успех, 1 - расхождения, 2 - сбой
'''
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.spec_parser import parse_spec


def escape_command(text):
    # Подготавливаем текст для сообщений GitHub Actions.
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def markdown(report):
    # Собираем читаемый отчёт с итогом и списком находок.
    lines = ["# API checks", "", f"Status: **{report['status']}**",
             f"Gate: **{report['gate']}**; threshold: {report['fail_on']}", "",
             f"Commit: {report.get('commit', 'unknown')}", ""]
    if report["status"] == "technical_error":
        lines.append(html.escape(report["error"]))
    else:
        lines += ["| Severity | Count |", "|---|---:|"]
        lines += [f"| {level} | {report['summary'][level]} |" for level in ("error", "warning", "info")]
        lines += ["", "## Findings", ""]
        for item in report["items"]:
            text = f"{item['severity']}: {item['endpoint']} — {item['category']}: {item['detail']}"
            lines += ["<pre>" + html.escape(text) + "</pre>", ""]
        if not report["items"]:
            lines.append("No drift detected.")
    return "\n".join(lines) + "\n"


def run(spec, source, output, fail_on):
    # Готовится папка отчётов
    output.mkdir(parents=True, exist_ok=True)
    (output / "error.log").unlink(missing_ok=True)

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "spec_path": str(spec), "src_path": str(source), "fail_on": fail_on}
    try:
        # Сохраняем версию кода и отпечаток спецификации
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        report["commit"] = commit.stdout.strip() if commit.returncode == 0 else "unknown"
        if not source.is_dir():
            raise ValueError(f"Source directory does not exist: {source}")
        report["spec_sha256"] = hashlib.sha256(spec.read_bytes()).hexdigest()

        # Запуск готовых модулей анализа и сравнения
        spec_model = parse_spec(spec)
        code_model = analyze_codebase(source)
        items = [item.to_dict() for item in compute_drift(spec_model, code_model)]

        # Считаем находки и решаем, провалена ли проверка
        counts = Counter(item["severity"] for item in items)
        blocked = ((fail_on == "error" and counts["error"] > 0) or (fail_on == "warning" and counts["error"] + counts["warning"] > 0))
        report.update(status="drift_detected" if items else "clean", items=items,
                      spec_endpoints=len(spec_model.endpoints), 
                      code_endpoints=len(code_model.endpoints),
                      summary={level: counts[level] for level in ("error", "warning", "info")},
                      gate="failed" if blocked else "passed")
        code = 1 if blocked else 0
    except Exception as error:
        # При сбое сохраняем причину и возвращаем код 2
        report.update(status="technical_error", gate="failed", error=str(error))
        (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        code = 2

    # Сохранение свежих отчётов
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = markdown(report)
    (output / "report.md").write_text(text, encoding="utf-8")

    # Добавляем отчёт на страницу запуска GitHub Actions
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(text)

    # Показываем находки и ошибки в журнале GitHub Actions
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if code == 2:
            print("::error::" + escape_command(report["error"]))
        else:
            for item in report["items"][:50]:
                level = "warning" if item["severity"] in {"error", "warning"} else "notice"
                print(f"::{level}::" + escape_command(f"{item['endpoint']}: {item['detail']}"))
            if code == 1:
                print("::error::API drift exceeds the selected threshold.")

    print(f"Status: {report['status']}; gate: {report['gate']}; reports: {output}")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fail-on", choices=["none", "error", "warning"], default="error")
    args = parser.parse_args()
    try:
        return run(args.spec, args.src, args.output, args.fail_on)
    except OSError as error:
        print(f"Cannot write CI reports: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
