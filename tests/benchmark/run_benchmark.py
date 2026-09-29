"""
Прогон бенчмарка для api-drift-agent.

Для каждого кейса в tests/benchmark/cases/<case>/:
  - запускается drift-check со spec и src из стандартных фикстур репозитория
  - результаты сопоставляются с expected.json
  - считаются precision / recall / F1

Запуск: python tests/benchmark/run_benchmark.py
"""
import json
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).parent
CASES_DIR = BENCH_DIR / "cases"
FIXTURES = BENCH_DIR.parent / "fixtures"

# для каждого кейса — где взять spec и src (относительно tests/fixtures)
CASE_SOURCES = {
    "01_drift_lab": {
        "spec": FIXTURES / "specs" / "drift_lab.yaml",
        "src":  FIXTURES / "apps" / "drift_lab_app",
    },
    "02_simple": {
        "spec": FIXTURES / "specs" / "simple.yaml",
        "src":  FIXTURES / "apps" / "simple_app",
    },
    "03_edge_cases": {
        "spec": CASES_DIR / "03_edge_cases" / "spec.yaml",
        "src":  CASES_DIR / "03_edge_cases" / "app",
    },
}

def normalize_location(loc):
    """Убираем индексные скобки и хвосты, чтобы матчинг был устойчивее."""
    if not loc:
        return ""
    loc = loc.replace("[]", "").strip(".")
    # для endpoint-level находок инструмент пишет "endpoint",
    # а в expected мы это поле опускаем — приводим к одному виду
    if loc == "endpoint":
        return ""
    return loc


def key(item):
    return (
        item.get("endpoint", "").strip(),
        item.get("category", "").strip(),
        normalize_location(item.get("location", "")),
    )


def run_case(case_name, spec_path, src_path):
    expected_file = CASES_DIR / case_name / "expected.json"
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    actual_file = CASES_DIR / case_name / "actual.json"

    print(f"\n=== {case_name} ===")
    print(f"  spec: {spec_path}")
    print(f"  src:  {src_path}")

    result = subprocess.run(
        [
            sys.executable, "-m", "drift_agent.cli",
            "--spec", str(spec_path),
            "--src", str(src_path),
            "--output-format", "json",
            "--output-file", str(actual_file),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # fallback на CLI-скрипт, если модуль не запускается
        result = subprocess.run(
            [
                "drift-check",
                "--spec", str(spec_path),
                "--src", str(src_path),
                "--output-format", "json",
                "--output-file", str(actual_file),
            ],
            capture_output=True,
            text=True,
        )

    if not actual_file.exists():
        print("  ОШИБКА: не создан actual.json")
        print("  stdout:", result.stdout[-500:])
        print("  stderr:", result.stderr[-500:])
        return None

    actual = json.loads(actual_file.read_text(encoding="utf-8"))

    actual_keys = {key(i) for i in actual.get("items", [])}
    expected_keys = {key(e) for e in expected["expected"]}

    tp = len(actual_keys & expected_keys)
    fp = len(actual_keys - expected_keys)
    fn = len(expected_keys - actual_keys)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    print(f"  TP={tp}  FP={fp}  FN={fn}")
    print(f"  Precision={precision:.3f}  Recall={recall:.3f}  F1={f1:.3f}")

    if fp:
        print("  False positives:")
        for k in sorted(actual_keys - expected_keys):
            print(f"    + {k}")
    if fn:
        print("  False negatives (пропущено):")
        for k in sorted(expected_keys - actual_keys):
            print(f"    - {k}")

    return {
        "case": case_name,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "fp_items": sorted("|".join(map(str, k)) for k in actual_keys - expected_keys),
        "fn_items": sorted("|".join(map(str, k)) for k in expected_keys - actual_keys),
    }


def main():
    results = []
    for case_name, paths in CASE_SOURCES.items():
        r = run_case(case_name, paths["spec"], paths["src"])
        if r:
            results.append(r)

    # итоговая таблица
    print("\n\n================ ИТОГО ================")
    print(f"{'case':<18} {'TP':>4} {'FP':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7}")
    for r in results:
        print(f"{r['case']:<18} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} "
              f"{r['precision']:>7.3f} {r['recall']:>7.3f} {r['f1']:>7.3f}")

    out = BENCH_DIR / "report.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()