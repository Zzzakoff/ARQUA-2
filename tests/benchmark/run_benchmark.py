"""
Прогон бенчмарка для api-drift-agent.

Находит все кейсы в tests/benchmark/cases/*/, для каждого:
  - находит spec.yaml и папку с кодом (app/, src/, ...)
  - запускает drift-check
  - сравнивает с expected.json
  - считает TP/FP/FN, precision, recall, F1, время
  - если передан --with-llm: дополнительно запускает drift-check --explain
    и сохраняет результат в llm_findings.json рядом с кейсом

Результат пишет в tests/benchmark/report.json

Запуск:
  python tests/benchmark/run_benchmark.py             (быстро, без LLM)
  python tests/benchmark/run_benchmark.py --with-llm  (долго, с LLM)
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).parent
CASES_DIR = BENCH_DIR / "cases"
REPORT_JSON = BENCH_DIR / "report.json"


def find_spec(case_dir):
    """Ищет YAML/JSON со спецификацией."""
    excluded = {"expected.json", "llm_findings.json", "actual.json"}
    patterns = ("*spec*.yaml", "*spec*.yml", "*openapi*.yaml", "*openapi*.yml",
                "*.yaml", "*.yml", "*.json")
    for pattern in patterns:
        for f in sorted(case_dir.glob(pattern)):
            if f.is_file() and f.name not in excluded:
                return f
    return None


def find_src(case_dir):
    """Ищет папку с исходным кодом."""
    for name in ("app", "src", "code", "service"):
        candidate = case_dir / name
        if candidate.is_dir():
            return candidate
    for sub in case_dir.iterdir():
        if sub.is_dir() and any(sub.rglob("*.py")):
            return sub
    return None


def normalize_location(loc):
    if not loc:
        return ""
    loc = loc.replace("[]", "").strip(".")
    if loc == "endpoint":
        return ""
    return loc


def key(item):
    return (
        item.get("endpoint", "").strip(),
        item.get("category", "").strip(),
        normalize_location(item.get("location", "")),
    )


def run_drift_check(spec, src, output_file, explain=False):
    """Запускает drift-check. Возвращает (ok, elapsed, stdout, stderr)."""
    args = [
        sys.executable, "-m", "drift_agent.cli",
        "--spec", str(spec),
        "--src", str(src),
        "--output-format", "json",
        "--output-file", str(output_file),
    ]
    if explain:
        args.append("--explain")

    start = time.perf_counter()
    result = subprocess.run(args, capture_output=True, text=True)
    elapsed = time.perf_counter() - start

    if result.returncode != 0 or not output_file.exists():
        # fallback на CLI-скрипт
        args_cli = args.copy()
        args_cli[0] = "drift-check"
        args_cli.pop(1)  # убираем "-m"
        args_cli.pop(1)  # убираем "drift_agent.cli"
        start = time.perf_counter()
        result = subprocess.run(args_cli, capture_output=True, text=True)
        elapsed = time.perf_counter() - start

    return output_file.exists(), elapsed, result.stdout, result.stderr


def run_case(case_dir, with_llm=False):
    spec = find_spec(case_dir)
    src = find_src(case_dir)
    expected_file = case_dir / "expected.json"

    if not spec:
        print(f"  [!] {case_dir.name}: не найдена спецификация — пропуск")
        return None
    if not src:
        print(f"  [!] {case_dir.name}: не найдена папка с кодом — пропуск")
        return None
    if not expected_file.exists():
        print(f"  [!] {case_dir.name}: не найден expected.json — пропуск")
        return None

    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    actual_file = case_dir / "actual.json"

    print(f"\n=== {case_dir.name} ===")
    print(f"  spec: {spec}")
    print(f"  src:  {src}")

    ok, elapsed, out, err = run_drift_check(spec, src, actual_file, explain=False)
    if not ok:
        print("  [!] Не создан actual.json")
        print("  stdout:", out[-500:])
        print("  stderr:", err[-500:])
        return None

    actual = json.loads(actual_file.read_text(encoding="utf-8"))

    actual_keys = {key(i) for i in actual.get("items", [])}
    expected_keys = {key(e) for e in expected.get("expected", [])}

    tp = len(actual_keys & expected_keys)
    fp = len(actual_keys - expected_keys)
    fn = len(expected_keys - actual_keys)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    print(f"  TP={tp}  FP={fp}  FN={fn}")
    print(f"  Precision={precision:.3f}  Recall={recall:.3f}  F1={f1:.3f}  Время={elapsed:.2f}с")

    if fp:
        print("  False positives:")
        for k in sorted(actual_keys - expected_keys):
            print(f"    + {k}")
    if fn:
        print("  False negatives (пропущено):")
        for k in sorted(expected_keys - actual_keys):
            print(f"    - {k}")

    # LLM-прогон (опционально)
    if with_llm:
        llm_file = case_dir / "llm_findings.json"
        print(f"  LLM-прогон (--explain)... это может занять время")
        ok_llm, llm_elapsed, _, err_llm = run_drift_check(
            spec, src, llm_file, explain=True
        )
        if ok_llm:
            print(f"  LLM готово за {llm_elapsed:.2f}с → {llm_file.name}")
        else:
            print(f"  [!] LLM не удалось. stderr: {err_llm[-500:]}")

    return {
        "case": case_dir.name,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "elapsed_sec": round(elapsed, 2),
    }


def main(with_llm=False):
    if not CASES_DIR.exists():
        print(f"Папка кейсов не найдена: {CASES_DIR}")
        return

    case_dirs = sorted(d for d in CASES_DIR.iterdir() if d.is_dir())
    if not case_dirs:
        print(f"Кейсы не найдены в {CASES_DIR}")
        return

    print(f"Найдено кейсов: {len(case_dirs)}")
    if with_llm:
        print("Режим: С LLM-объяснениями (--with-llm)")

    results = []
    for case_dir in case_dirs:
        r = run_case(case_dir, with_llm=with_llm)
        if r:
            results.append(r)

    if not results:
        print("Ни один кейс не обработан.")
        return

    print("\n================ ИТОГО ================")
    print(f"{'case':<20} {'TP':>4} {'FP':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7} {'Время':>8}")
    for r in results:
        print(f"{r['case']:<20} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} "
              f"{r['precision']:>7.3f} {r['recall']:>7.3f} {r['f1']:>7.3f} "
              f"{r['elapsed_sec']:>7.2f}с")

    REPORT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nОтчёт: {REPORT_JSON}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true",
                        help="Прогнать также drift-check --explain для каждого кейса")
    args = parser.parse_args()
    main(with_llm=args.with_llm)