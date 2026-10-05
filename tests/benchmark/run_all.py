"""
Полный цикл бенчмарка: прогон тестов + генерация PDF.

Запуск: python tests/benchmark/run_all.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import run_benchmark
import generate_pdf


def main():
    run_benchmark.main()

    generate_pdf.generate_pdf()

    print("\nГотово")


if __name__ == "__main__":
    main()