"""Safe archive inspection and deterministic, side-effect-free FastAPI/OpenAPI scan."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

MAX_ZIP_COMPRESSED = 30 * 1024 * 1024
MAX_UNPACKED = 100 * 1024 * 1024
MAX_FILES = 1600
MAX_FILE = 12 * 1024 * 1024
EXCLUDED = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.idea'}
SPEC_NAMES = {'openapi.yaml', 'openapi.yml', 'openapi.json', 'swagger.yaml', 'swagger.yml', 'swagger.json'}


class UploadError(ValueError):
    pass


def inspect_archive(fileobj):
    """Validate ZIP's entire directory before writing any file to disk."""
    fileobj.seek(0)
    try:
        with zipfile.ZipFile(fileobj) as archive:
            entries = []
            total = 0
            count = 0
            for info in archive.infolist():
                raw = info.filename.replace('\\', '/')
                path = posixpath.normpath(raw)
                if (not raw or '\x00' in raw or raw.startswith('/') or re.match(r'^[A-Za-z]:', raw)
                        or path == '..' or path.startswith('../') or path.startswith('/') or path == '.'):
                    raise UploadError('ZIP содержит небезопасный путь.')
                parts = Path(path).parts
                if any(part in EXCLUDED for part in parts):
                    continue
                if len(parts) > 25:
                    raise UploadError('Слишком большая вложенность каталогов.')
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UploadError('Символические ссылки в ZIP запрещены.')
                if info.is_dir():
                    continue
                count += 1
                total += info.file_size
                if count > MAX_FILES or total > MAX_UNPACKED or info.file_size > MAX_FILE:
                    raise UploadError('ZIP превышает ограничения на количество или размер файлов.')
                entries.append((info, path))
            if not any(path.lower().endswith('.py') for _, path in entries):
                raise UploadError('ZIP не содержит Python-файлов (нужен проект FastAPI).')
            if archive.testzip() is not None:
                raise UploadError('ZIP содержит повреждённые данные.')
            return entries
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise UploadError('Файл не является корректным ZIP-архивом.') from exc
    finally:
        fileobj.seek(0)


def extract_project(archive_path: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    try:
        with archive_path.open('rb') as handle:
            entries = inspect_archive(handle)
        with zipfile.ZipFile(archive_path) as archive:
            for info, rel in entries:
                dest = (output / rel).resolve()
                if not dest.is_relative_to(output.resolve()):
                    raise UploadError('Небезопасный путь внутри ZIP.')
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, dest.open('wb') as dst:
                    shutil.copyfileobj(src, dst, length=65536)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    # Collapse a single wrapping folder, while keeping absolute root stable.
    node = output
    for _ in range(5):
        children = list(node.iterdir())
        if len(children) == 1 and children[0].is_dir():
            node = children[0]
        else:
            break
    return node


def find_openapi(project_root: Path):
    candidates = [p for p in project_root.rglob('*') if p.is_file() and p.name.lower() in SPEC_NAMES]
    candidates.sort(key=lambda p: (len(p.relative_to(project_root).parts), p.name.lower()))
    return candidates[0] if candidates else None


def analyze(project_root: Path, spec_path: Path):
    # This does NOT import or execute the uploaded service; it parses source text with ast.
    from drift_agent.code_analyzer import analyze_codebase
    from drift_agent.diff_engine import compute_drift
    from drift_agent.spec_parser import parse_spec
    spec_model = parse_spec(spec_path)
    code_model = analyze_codebase(project_root)
    drift_items = compute_drift(spec_model, code_model)
    counts = Counter(item.severity for item in drift_items)
    return drift_items, {
        'run_id': uuid.uuid4().hex[:12],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'spec_path': spec_path.name,
        'src_path': project_root.name,
        'spec_endpoints': len(spec_model.endpoints),
        'code_endpoints': len(code_model.endpoints),
        'items': [item.to_dict() for item in drift_items],
        'summary': {**{k: counts[k] for k in ('error', 'warning', 'info')}, 'total': len(drift_items)},
        'taxonomy_summary': dict(Counter(item.taxonomy.value for item in drift_items)),
        'priority_summary': dict(Counter(item.priority for item in drift_items)),
    }


def project_workspace(scan_id: int):
    # Data is outside static paths and no file-serving route is configured.
    return Path(settings.MEDIA_ROOT) / 'private_projects' / str(scan_id)


def file_hash(path: Path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def write_report(scan, report):
    from django.core.files.base import ContentFile
    serialized = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    scan.drift_report.save(f'scan-{scan.pk}-report.json', ContentFile(serialized), save=False)
