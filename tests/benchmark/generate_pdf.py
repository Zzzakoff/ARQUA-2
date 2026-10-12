"""
Генерация PDF-отчёта по результатам бенчмарка.

Читает report.json, подхватывает llm_findings.json и actual.json из кейсов.
Описание расхождения: если есть перевод в REASONING_RU — русский, иначе английский.

Запуск: python tests/benchmark/generate_pdf.py
"""
import json
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_REGULAR = "Arial"
FONT_BOLD = "Arial-Bold"
pdfmetrics.registerFont(TTFont(FONT_REGULAR, "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "C:/Windows/Fonts/arialbd.ttf"))

BENCH_DIR = Path(__file__).parent
CASES_DIR = BENCH_DIR / "cases"
REPORT_JSON = BENCH_DIR / "report.json"
REPORT_PDF = BENCH_DIR / "report.pdf"

CATEGORY_RU = {
    "missing_endpoint":  "отсутствующий эндпоинт",
    "ghost_endpoint":    "лишний эндпоинт",
    "additive_drift":    "добавочное поле",
    "destructive_drift": "пропавшее поле",
    "type_drift":        "расхождение типа",
    "nullability_drift": "расхождение nullable",
    "required_drift":    "расхождение обязательности",
    "status_code_drift": "расхождение кода ответа",
    "parameter_drift":   "расхождение параметра",
}

SOURCE_OF_TRUTH_RU = {
    "SPEC": "SPEC — спецификация",
    "CODE": "CODE — код",
    "AMBIGUOUS": "AMBIGUOUS — неоднозначно",
}

# Переводы reasoning от LLM. Ключ — начало английского текста.
REASONING_RU = {
    "The endpoint is declared in":
        "Эндпоинт объявлен в спецификации, но отсутствует в коде.",
    "The endpoint GET /extra exist":
        "Эндпоинт GET /extra есть в коде, но отсутствует в спецификации.",
    "The spec defines a schema for":
        "Спецификация описывает схему ответа, но в коде схема не объявлена.",
    "The spec indicates that the '":
        "Спецификация требует поле 'count', но в коде оно не обязательно.",
    "The spec explicitly states th":
        "Спецификация требует тип 'integer', а в коде тип неизвестен — расхождение.",
}


def ru_reasoning(text):
    """Русский перевод, если есть в словаре. Иначе — оригинал."""
    if not text:
        return "—"
    for prefix, ru in REASONING_RU.items():
        if text.startswith(prefix):
            return ru
    return text


def cell(text, bold=False, size=8, align="CENTER"):
    style = ParagraphStyle(
        "cell",
        fontName=FONT_BOLD if bold else FONT_REGULAR,
        fontSize=size, leading=size + 2,
        alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align],
    )
    return Paragraph(str(text), style)


def category_cell(code):
    ru = CATEGORY_RU.get(code, "")
    s1 = ParagraphStyle("c1", fontName=FONT_BOLD, fontSize=8, leading=10, alignment=1)
    s2 = ParagraphStyle("c2", fontName=FONT_REGULAR, fontSize=7, leading=9,
                        alignment=1, textColor=colors.HexColor("#555555"))
    return [Paragraph(code, s1), Paragraph(ru, s2)]


def load_case_details(case_name):
    case_dir = CASES_DIR / case_name
    items = []
    llm_findings = []

    actual_file = case_dir / "actual.json"
    if actual_file.exists():
        actual = json.loads(actual_file.read_text(encoding="utf-8"))
        items = actual.get("items", [])

    llm_file = case_dir / "llm_findings.json"
    if llm_file.exists():
        llm = json.loads(llm_file.read_text(encoding="utf-8"))
        llm_findings = llm.get("findings") or llm.get("agent_findings") or []

    return items, llm_findings


def build_metrics_table(results):
    header = ["Кейс", "TP", "FP", "FN", "Precision", "Recall", "F1", "Время, с"]
    rows = [[cell(h, bold=True, size=10) for h in header]]
    for r in results:
        rows.append([
            cell(r["case"], size=9), cell(r["tp"], size=9), cell(r["fp"], size=9),
            cell(r["fn"], size=9), cell(f"{r['precision']:.3f}", size=9),
            cell(f"{r['recall']:.3f}", size=9), cell(f"{r['f1']:.3f}", size=9),
            cell(f"{r['elapsed_sec']:.2f}", size=9),
        ])
    table = Table(rows, colWidths=[4.5*cm, 1.3*cm, 1.3*cm, 1.3*cm, 2.2*cm, 2.0*cm, 1.8*cm, 2.2*cm],
                  hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def build_summary_table(results):
    total_tp = sum(r["tp"] for r in results)
    total_fp = sum(r["fp"] for r in results)
    total_fn = sum(r["fn"] for r in results)
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    rows = [
        [cell("Всего TP", bold=True, size=10), cell(str(total_tp), size=10)],
        [cell("Всего FP", bold=True, size=10), cell(str(total_fp), size=10)],
        [cell("Всего FN", bold=True, size=10), cell(str(total_fn), size=10)],
        [cell("Общий Precision", bold=True, size=10), cell(f"{precision:.3f}", size=10)],
        [cell("Общий Recall", bold=True, size=10), cell(f"{recall:.3f}", size=10)],
        [cell("Общий F1", bold=True, size=10), cell(f"{f1:.3f}", size=10)],
    ]
    table = Table(rows, colWidths=[6*cm, 4*cm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ECF0F1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_findings_table(items, llm_findings):
    llm_by_id = {f.get("drift_item_id"): f for f in llm_findings}
    header = ["Endpoint", "Категория", "Место", "Описание", "Источник истины", "Уверенность"]
    rows = [[cell(h, bold=True, size=9) for h in header]]
    for item in items:
        llm = llm_by_id.get(item.get("id"), {})
        reasoning = ru_reasoning(llm.get("reasoning", "—"))
        rows.append([
            cell(item.get("endpoint", "—"), size=8),
            category_cell(item.get("category", "—")),
            cell(item.get("location", "—"), size=8),
            cell(reasoning, size=8, align="LEFT"),
            cell(SOURCE_OF_TRUTH_RU.get(llm.get("source_of_truth"), "—"), size=8),
            cell(llm.get("confidence", "—"), size=8),
        ])
    table = Table(rows, colWidths=[3.3*cm, 3.5*cm, 3.0*cm, 8.5*cm, 3.2*cm, 2.0*cm],
                  hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def generate_pdf():
    if not REPORT_JSON.exists():
        print(f"Не найден {REPORT_JSON}. Сначала запустите run_benchmark.py")
        return

    results = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

    doc = SimpleDocTemplate(
        str(REPORT_PDF),
        pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Heading1"],
                                  fontName=FONT_BOLD, fontSize=18, spaceAfter=6, alignment=0)
    subtitle_style = ParagraphStyle("S", parent=styles["Normal"],
                                     fontName=FONT_REGULAR, fontSize=10,
                                     textColor=colors.grey, spaceAfter=20, alignment=0)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                        fontName=FONT_BOLD, fontSize=13, spaceBefore=14, spaceAfter=8, alignment=0)
    body = ParagraphStyle("B", parent=styles["Normal"],
                          fontName=FONT_REGULAR, fontSize=10, leading=14, alignment=0)

    story = []
    story.append(Paragraph("Отчёт по опытной эксплуатации", title_style))
    story.append(Paragraph(
        "Инструмент: api-drift-agent. Проверка соответствия OpenAPI-спецификации и FastAPI-кода.",
        subtitle_style,
    ))
    story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Результаты по кейсам", h2))
    story.append(build_metrics_table(results))
    story.append(Spacer(1, 15))

    story.append(Paragraph("Сводные метрики", h2))
    story.append(build_summary_table(results))
    story.append(Spacer(1, 15))

    for r in results:
        items, llm_findings = load_case_details(r["case"])
        if not items:
            continue
        story.append(Paragraph(f"Кейс: {r['case']}", h2))
        story.append(build_findings_table(items, llm_findings))
        story.append(Spacer(1, 12))

    doc.build(story)
    print(f"PDF-отчёт создан: {REPORT_PDF}")


if __name__ == "__main__":
    generate_pdf()