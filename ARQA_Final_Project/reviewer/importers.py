from django.db import transaction

from .models import Proposal


CATEGORY_LABELS = {
    'missing_endpoint': 'Endpoint отсутствует в коде',
    'ghost_endpoint': 'Endpoint отсутствует в спецификации',
    'additive_drift': 'Недокументированное поле',
    'destructive_drift': 'Поле отсутствует в коде',
    'type_drift': 'Расхождение типов',
    'nullability_drift': 'Расхождение nullable',
    'required_drift': 'Расхождение обязательности',
    'status_code_drift': 'Расхождение HTTP-статусов',
    'parameter_drift': 'Расхождение параметров',
}


def split_endpoint(endpoint):
    parts = str(endpoint or '').strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].isalpha():
        return parts[0].lower(), parts[1]
    return '', str(endpoint or '').strip()


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def import_drift_report(scan, payload):
    findings = {
        str(item.get('drift_item_id')): item
        for item in payload.get('findings', [])
        if isinstance(item, dict) and item.get('drift_item_id')
    }
    summary = payload.get('summary') or {}
    scan.run_id = str(payload.get('run_id') or '')
    scan.spec_path = str(payload.get('spec_path') or '')
    scan.source_path = str(payload.get('src_path') or '')
    scan.spec_endpoints = int(payload.get('spec_endpoints') or 0)
    scan.code_endpoints = int(payload.get('code_endpoints') or 0)
    scan.error_count = int(summary.get('error') or 0)
    scan.warning_count = int(summary.get('warning') or 0)
    scan.info_count = int(summary.get('info') or 0)
    scan.drift_count = int(summary.get('total') or len(payload.get('items', [])))
    scan.save(update_fields=[
        'run_id', 'spec_path', 'source_path', 'spec_endpoints', 'code_endpoints',
        'error_count', 'warning_count', 'info_count', 'drift_count',
    ])

    created = []
    with transaction.atomic():
        for item in payload.get('items', []):
            drift_id = str(item.get('id') or '')
            finding = findings.get(drift_id) or {}
            patch = finding.get('patch') if isinstance(finding.get('patch'), dict) else {}
            method, path = split_endpoint(item.get('endpoint'))
            category = str(item.get('category') or '')
            source = str(finding.get('source_of_truth') or '')
            confidence = str(finding.get('confidence') or '')
            reasoning = str(finding.get('reasoning') or item.get('detail') or '')
            patch_content = _text(patch.get('content'))
            requires_manual_review = bool(item.get('requires_review')) or source.upper() == 'AMBIGUOUS' or confidence.lower() == 'low'
            title = CATEGORY_LABELS.get(category, category.replace('_', ' ').strip().capitalize())
            proposal = Proposal.objects.create(
                scan=scan,
                drift_id=drift_id,
                title=title,
                path=path,
                method=method,
                proposal_type=category,
                severity=str(item.get('severity') or ''),
                location=str(item.get('location') or ''),
                reason=reasoning,
                spec_evidence=_text(item.get('spec_evidence')),
                code_evidence=_text(item.get('code_evidence')),
                source_of_truth=source,
                confidence=confidence,
                patch_target=str(patch.get('target') or ''),
                patch_type=str(patch.get('patch_type') or ''),
                patch_location=str(patch.get('location') or ''),
                patch_content=patch_content,
                after_text=patch_content,
                requires_manual_review=requires_manual_review,
                taxonomy=str(item.get('taxonomy') or ''),
                priority=str(item.get('priority') or ''),
                source_file=str(item.get('source_file') or ''),
                source_line=item.get('source_line') if isinstance(item.get('source_line'), int) and item['source_line'] > 0 else None,
                impact=str(finding.get('impact') or ''),
                risks=str(finding.get('risks') or ''),
                recommendation=str(finding.get('recommendation') or ''),
                llm_reasoning=str(finding.get('llm_reasoning') or ''),
                llm_confidence=str(finding.get('llm_confidence') or ''),
                explanation_origin=str(finding.get('explanation_origin') or ''),
            )
            created.append(proposal)
    return created
