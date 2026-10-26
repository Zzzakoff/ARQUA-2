import importlib.util
import json
from pathlib import Path


CI_SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "ci_check.py"
spec = importlib.util.spec_from_file_location("ci_check", CI_SCRIPT)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def _example(tmp_path: Path):
    source = tmp_path / "app"
    source.mkdir()
    (source / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.0.3",
                "info": {"title": "Test", "version": "1.0"},
                "paths": {"/health": {"get": {"responses": {"200": {"description": "OK"}}}}},
            }
        ),
        encoding="utf-8",
    )
    return spec_path, source, tmp_path / "reports"


def _read_report(output: Path):
    return json.loads((output / "report.json").read_text(encoding="utf-8"))


def _check_technical_error(spec_path: Path, source: Path, output: Path):
    output.mkdir()
    (output / "report.json").write_text('{"status": "clean"}', encoding="utf-8")

    result = ci.run(spec_path, source, output, "none")

    assert result == 2
    assert _read_report(output)["status"] == "technical_error"
    assert "technical_error" in (output / "report.md").read_text(encoding="utf-8")
    assert (output / "error.log").exists()


def test_missing_endpoint_report_only(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)

    result = ci.run(spec_path, source, output, "none")

    report = _read_report(output)
    assert result == 0
    assert report["status"] == "drift_detected"
    assert report["items"][0]["category"] == "missing_endpoint"
    assert len(report["spec_sha256"]) == 64
    assert "missing_endpoint" in (output / "report.md").read_text(encoding="utf-8")


def test_missing_endpoint_error_threshold(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)

    result = ci.run(spec_path, source, output, "error")

    assert result == 1
    assert _read_report(output)["items"][0]["category"] == "missing_endpoint"


def test_missing_endpoint_warning_threshold(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)

    result = ci.run(spec_path, source, output, "warning")

    assert result == 1
    assert _read_report(output)["items"][0]["category"] == "missing_endpoint"


def test_clean_api_and_github_summary(tmp_path: Path, monkeypatch):
    spec_path, source, output = _example(tmp_path)
    document = json.loads(spec_path.read_text(encoding="utf-8"))
    document["paths"] = {}
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    result = ci.run(spec_path, source, output, "error")

    assert result == 0
    assert _read_report(output)["status"] == "clean"
    assert "No drift detected" in summary.read_text(encoding="utf-8")


def test_invalid_spec(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)
    spec_path.write_text("{broken", encoding="utf-8")

    _check_technical_error(spec_path, source, output)


def test_missing_source(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)

    _check_technical_error(spec_path, source / "absent", output)


def test_missing_spec(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)
    spec_path.unlink()

    _check_technical_error(spec_path, source, output)


def test_warning_threshold(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)
    document = json.loads(spec_path.read_text(encoding="utf-8"))
    document["paths"] = {}
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    (source / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n'
        '@app.get("/health")\ndef health():\n    return {}\n',
        encoding="utf-8",
    )

    error_result = ci.run(spec_path, source, output, "error")
    warning_result = ci.run(spec_path, source, output, "warning")

    assert error_result == 0
    assert warning_result == 1


def test_annotation_escape():
    text = ci.escape_command("a%\n::error::b\r")

    assert text == "a%25%0A::error::b%0D"


def test_success_clears_previous_error_log(tmp_path: Path):
    spec_path, source, output = _example(tmp_path)
    output.mkdir()
    (output / "error.log").write_text("previous failure", encoding="utf-8")

    result = ci.run(spec_path, source, output, "none")

    assert result == 0
    assert not (output / "error.log").exists()


def test_report_escapes_untrusted_content():
    report = {
        "status": "technical_error",
        "gate": "failed",
        "fail_on": "none",
        "error": "<script>alert(1)</script>",
    }

    text = ci.markdown(report)

    assert "<script>" not in text
    assert "&lt;script&gt;" in text
