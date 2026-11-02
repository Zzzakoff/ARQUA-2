"""
Генерация PDF-отчёта по результатам бенчмарка.

Читает report.json (создаётся run_benchmark.py), рисует таблицу
с метриками и сохраняет в PDF.

Запуск: python tests/benchmark/generate_pdf.py
"""
import json
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Подключаем шрифты с поддержкой кириллицы (системные шрифты Windows)
FONT_REGULAR = "Arial"
FONT_BOLD = "Arial-Bold"

pdfmetrics.registerFont(TTFont(FONT_REGULAR, "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "C:/Windows/Fonts/arialbd.ttf"))

BENCH_DIR = Path(__file__).parent
REPORT_JSON = BENCH_DIR / "report.json"
REPORT_PDF = BENCH_DIR / "report.pdf"


def build_table(results):
    """Собирает таблицу с метриками."""
    header = ["Кейс", "TP", "FP", "FN", "Precision", "Recall", "F1", "Время, с"]
    rows = [header]
    for r in results:
        rows.append([
            r["case"],
            str(r["tp"]),
            str(r["fp"]),
            str(r["fn"]),
            f"{r['precision']:.3f}",
            f"{r['recall']:.3f}",
            f"{r['f1']:.3f}",
            f"{r['elapsed_sec']:.2f}",
        ])

    table = Table(rows, colWidths=[4.2*cm, 1.3*cm, 1.3*cm, 1.3*cm, 2.2*cm, 2.0*cm, 1.8*cm, 2.2*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def build_summary(results):
    """Общая сводка по всем кейсам."""
    total_tp = sum(r["tp"] for r in results)
    total_fp = sum(r["fp"] for r in results)
    total_fn = sum(r["fn"] for r in results)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    rows = [
        ["Всего TP", str(total_tp)],
        ["Всего FP", str(total_fp)],
        ["Всего FN", str(total_fn)],
        ["Общий Precision", f"{precision:.3f}"],
        ["Общий Recall", f"{recall:.3f}"],
        ["Общий F1", f"{f1:.3f}"],
    ]
    table = Table(rows, colWidths=[6*cm, 4*cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), FONT_BOLD),
        ("FONTNAME", (1, 0), (1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ECF0F1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def generate_pdf():
    results = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

    doc = SimpleDocTemplate(
        str(REPORT_PDF),
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        fontName=FONT_BOLD, fontSize=18, spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontName=FONT_REGULAR, fontSize=10,
        textColor=colors.grey, spaceAfter=20
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontName=FONT_BOLD, fontSize=13,
        spaceBefore=14, spaceAfter=8
    )
    body = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontName=FONT_REGULAR, fontSize=10, leading=14
    )

    story = []

    story.append(Paragraph("Отчёт по опытной эксплуатации", title_style))
    story.append(Paragraph(
        "Инструмент: api-drift-agent. Проверка соответствия OpenAPI-спецификации и FastAPI-кода.",
        subtitle_style,
    ))
    story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Результаты по кейсам", h2))
    story.append(build_table(results))
    story.append(Spacer(1, 15))

    story.append(Paragraph("Сводные метрики", h2))
    story.append(build_summary(results))
    story.append(Spacer(1, 15))

    story.append(Paragraph("Обозначения метрик", h2))
    story.append(Paragraph(
        "<b>TP (True Positive)</b> — инструмент нашёл расхождение, и оно реально есть.<br/>"
        "<b>FP (False Positive)</b> — инструмент нашёл расхождение, которого нет (ложное срабатывание).<br/>"
        "<b>FN (False Negative)</b> — расхождение есть, но инструмент его не нашёл (пропуск).<br/>"
        "<b>Precision</b> = TP / (TP + FP) — доля правильных находок среди всех найденных.<br/>"
        "<b>Recall</b> = TP / (TP + FN) — доля найденных расхождений среди всех реально существующих.<br/>"
        "<b>F1</b> — среднее гармоническое между Precision и Recall.",
        body,
    ))
    story.append(Spacer(1, 15))

    doc.build(story)
    print(f"PDF-отчёт создан: {REPORT_PDF}")


if __name__ == "__main__":
    generate_pdf()