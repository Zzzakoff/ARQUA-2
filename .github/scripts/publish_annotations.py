import json
import sys

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'drift-report.json'
    with open(path, 'r', encoding='utf-8') as f:
        report = json.load(f)

    spec_path = report.get('spec_path', 'openapi.yaml')
    items = report.get('items', [])

    # Заголовок со сводкой
    summary = report.get('summary', {})
    print(f"::notice title=Drift summary::"
          f"error={summary.get('error',0)}, "
          f"warning={summary.get('warning',0)}, "
          f"info={summary.get('info',0)}, "
          f"total={summary.get('total',0)}")

    for item in items:
        severity = item.get('severity', 'warning').lower()
        level = {'error': 'error', 'warning': 'warning'}.get(severity, 'notice')

        endpoint = item.get('endpoint', '')
        category = item.get('category', '')
        location = item.get('location', '')
        detail = item.get('detail', '')
        drift_id = item.get('id', '')

        # GitHub annotations: file + line обязательны для привязки к файлу
        # Привязываем к spec-файлу, строку не указываем line=1
        message = f"[{category}] {endpoint} @ {location} — {detail} (id={drift_id})"
        message = message.replace('\n', ' ').replace('\r', ' ')

        print(f"::{level} file={spec_path},line=1::{message}")

if __name__ == '__main__':
    main()