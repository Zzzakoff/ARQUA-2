"""
Генерация PDF-отчёта по результатам бенчмарка.
"""
import json
import re
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


def humanize_location(loc):
    if not loc or loc == "endpoint":
        return "эндпоинт целиком"
    parts = loc.split(".")
    if parts[0] == "response" and len(parts) >= 2:
        code = parts[1]
        tail = ".".join(parts[2:]) if len(parts) > 2 else ""
        if tail.endswith("schema"):
            tail = tail[:-7].rstrip(".") or "схема"
        if tail:
            return f"«{tail}» в ответе {code}"
        return f"ответ {code}"
    if parts[0] == "request_body":
        tail = ".".join(parts[1:]) or "тело"
        if tail.startswith("schema."):
            tail = tail[7:]
        return f"поле «{tail}» в теле запроса"
    if parts[0] == "parameters" and len(parts) >= 2:
        return f"параметр «{parts[1]}»"
    return loc


def ru_description(item):
    cat = item.get("category", "")
    endpoint = item.get("endpoint", "—")
    loc = item.get("location", "")
    spec_ev = item.get("spec_evidence")
    code_ev = item.get("code_evidence")
    place = humanize_location(loc)

    if cat == "missing_endpoint":
        return f"Эндпоинт {endpoint} объявлен в спецификации, но отсутствует в коде."
    if cat == "ghost_endpoint":
        return f"Эндпоинт {endpoint} есть в коде, но не описан в спецификации."
    if cat == "additive_drift":
        return f"В {place} код возвращает поле, которого нет в спецификации."
    if cat == "destructive_drift":
        return f"В {place} спецификация описывает поле, которого нет в коде."
    if cat == "type_drift":
        return f"В {place} тип не совпадает: спека — {spec_ev}, код — {code_ev}."
    if cat == "nullability_drift":
        return f"В {place} различается nullable: спека — {spec_ev}, код — {code_ev}."
    if cat == "required_drift":
        return f"В {place} различается обязательность: спека — {spec_ev}, код — {code_ev}."
    if cat == "status_code_drift":
        who = "спеке" if spec_ev else "коде"
        return f"Код ответа {loc} присутствует только в {who}."
    if cat == "parameter_drift":
        who = "спеке" if spec_ev else "коде"
        return f"В {place} параметр присутствует только в {who}."
    return "—"


def build_evidence_text(item, src_dir):
    """Собирает доказательства из спеки, кода и ищет файл/строку."""
    spec_ev = item.get("spec_evidence")
    code_ev = item.get("code_evidence")
    
    parts = []
    if spec_ev:
        parts.append(f"Спека: {spec_ev}")
    if code_ev:
        parts.append(f"Код: {code_ev}")
        
    # Поиск файла и строки
    loc = item.get("location", "")
    search_word = ""
    if "." in loc:
        search_word = loc.split(".")[-1].replace("[]", "")
    
    if search_word and src_dir.exists():
        # Ищем по частям слова (например, X-Trace-Id -> x_trace_id)
        search_parts = [p.lower() for p in re.split(r'[-_]', search_word) if len(p) > 2]
        
        found = False
        for py_file in src_dir.rglob("*.py"):
            if found: break
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines, start=1):
                    line_lower = line.lower()
                    # Проверяем, что все части слова есть в строке
                    if all(part in line_lower for part in search_parts):
                        rel_path = py_file.relative_to(src_dir)
                        parts.append(f"Строка: {rel_path}:{i}")
                        found = True
                        break
            except Exception:
                pass
                
    if not parts:
        return "—"
    return "\n".join(parts)


def load_case_details(case_name):
    case_dir = CASES_DIR / case_name
    items = []
    llm_findings = []
    
    # Ищем папку с кодом
    src_dir = case_dir / "app"
    if not src_dir.exists():
        src_dir = case_dir / "src"
    if not src_dir.exists():
        src_dir = None

    actual_file = case_dir / "actual.json"
    if actual_file.exists():
        actual = json.loads(actual_file.read_text(encoding="utf-8"))
        items = actual.get("items", [])

    llm_file = case_dir / "llm_findings.json"
    if llm_file.exists():
        llm = json.loads(llm_file.read_text(encoding="utf-8"))
        llm_findings = llm.get("findings") or llm.get("agent_findings") or []

    return items, llm_findings, src_dir


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


def build_findings_table(items, llm_findings, src_dir):
    llm_by_id = {f.get("drift_item_id"): f for f in llm_findings}
    header = ["Endpoint", "Категория", "Место", "Описание", "Доказательства (файл:строка)", "Источник", "Уверенность", "Ручной разбор"]
    rows = [[cell(h, bold=True, size=9) for h in header]]
    
    for item in items:
        llm = llm_by_id.get(item.get("id"), {})
        source = llm.get("source_of_truth")
        
        # Пункт 3: признак ручного разбора
        manual = "Да" if source == "AMBIGUOUS" else "Нет"
        
        rows.append([
            cell(item.get("endpoint", "—"), size=8),
            category_cell(item.get("category", "—")),
            cell(item.get("location", "—"), size=8),
            cell(ru_description(item), size=8, align="LEFT"),
            cell(build_evidence_text(item, src_dir), size=7, align="LEFT"), # Пункт 1: доказательства
            cell(SOURCE_OF_TRUTH_RU.get(source, "—"), size=8),
            cell(llm.get("confidence", "—"), size=8),
            cell(manual, size=8),
        ])
        
    table = Table(rows, colWidths=[2.8*cm, 2.8*cm, 2.2*cm, 4.8*cm, 5.0*cm, 2.2*cm, 1.5*cm, 1.5*cm],
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
        leftMargin=1.0*cm, rightMargin=1.0*cm,
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
        # Вот эта строчка должна возвращать ТРИ значения
        items, llm_findings, src_dir = load_case_details(r["case"])
        if not items:
            continue
        story.append(Paragraph(f"Кейс: {r['case']}", h2))
        # Передаем все три в таблицу
        story.append(build_findings_table(items, llm_findings, src_dir))
        story.append(Spacer(1, 12))

    doc.build(story)
    print(f"PDF-отчёт создан: {REPORT_PDF}")


if __name__ == "__main__":
    generate_pdf()