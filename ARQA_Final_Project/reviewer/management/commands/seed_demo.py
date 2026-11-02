import json
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from reviewer.importers import import_drift_report
from reviewer.models import Scan


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        report_path = Path(__file__).resolve().parents[3] / 'sample_data' / 'simple_report.json'
        payload = json.loads(report_path.read_text(encoding='utf-8'))
        scan = Scan(name='Демо drift report')
        scan.drift_report.save(
            'simple_report.json',
            ContentFile(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')),
            save=True,
        )
        imported = import_drift_report(scan, payload)
        self.stdout.write(self.style.SUCCESS(f'Демо-скан создан. Импортировано: {len(imported)}.'))
