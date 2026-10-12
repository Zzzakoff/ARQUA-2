"""
Полный цикл бенчмарка: прогон тестов + генерация PDF.

Запуск:
  python tests/benchmark/run_all.py             (быстро, без LLM)
  python tests/benchmark/run_all.py --with-llm  (с LLM, долго)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import run_benchmark
import generate_pdf


def main(with_llm=False):
    print("=" * 50)
    print("Шаг 1/2: прогон бенчмарка" + (" (с LLM)" if with_llm else ""))
    print("=" * 50)
    run_benchmark.main(with_llm=with_llm)

    print("\n" + "=" * 50)
    print("Шаг 2/2: генерация PDF-отчёта")
    print("=" * 50)
    generate_pdf.generate_pdf()

    print("\nГотово.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true",
                        help="Прогнать также drift-check --explain (долго)")
    args = parser.parse_args()
    main(with_llm=args.with_llm)