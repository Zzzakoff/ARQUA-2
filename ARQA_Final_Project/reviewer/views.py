import json
from difflib import unified_diff

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import can_review, reviewer_required
from .forms import ScanForm, ProjectScanForm
from .importers import import_drift_report
from .models import Proposal, Scan


def visible_scans(request):
    from django.db.models import Q
    if request.user.is_staff:
        return Scan.objects.order_by('-created_at')
    if request.user.is_authenticated:
        return Scan.objects.filter(Q(project_archive='') | Q(created_by=request.user)).order_by('-created_at')
    return Scan.objects.filter(project_archive='').order_by('-created_at')


def index(request):
    if request.method == 'POST':
        form = ScanForm(request.POST, request.FILES)
        if form.is_valid():
            scan = form.save(commit=False)
            scan.name = form.cleaned_data['name']
            if request.user.is_authenticated:
                scan.created_by = request.user
            scan.save()
            payload = form.cleaned_data['report_payload']
            imported = import_drift_report(scan, payload)
            messages.success(request, f'Скан «{scan.name}» создан. Импортировано расхождений: {len(imported)}.')
            return redirect('scan_detail', scan.id)
        return render(request, 'reviewer/index.html', {
            'form': form, 'project_form': ProjectScanForm(),
            'scans': visible_scans(request),
        })

    return render(request, 'reviewer/index.html', {
        'form': ScanForm(), 'project_form': ProjectScanForm(),
        'scans': visible_scans(request),
    })


def scan_detail(request, scan_id):
    scan = get_object_or_404(Scan, pk=scan_id)
    if scan.project_archive and (not request.user.is_authenticated or
                                 (scan.created_by_id != request.user.pk and not request.user.is_staff)):
        raise Http404('Сканирование не найдено.')
    qs = scan.proposals.order_by('-created_at')

    status_filter = request.GET.get('status', '')
    severity_filter = request.GET.get('severity', '')
    category_filter = request.GET.get('category', '')

    if status_filter in {'pending', 'accepted', 'rejected', 'edited'}:
        qs = qs.filter(status=status_filter)
    if severity_filter in {'error', 'warning', 'info'}:
        qs = qs.filter(severity=severity_filter)
    if category_filter:
        qs = qs.filter(proposal_type=category_filter)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    all_proposals = scan.proposals.all()
    categories = list(
        all_proposals.exclude(proposal_type='')
        .values_list('proposal_type', flat=True)
        .distinct()
        .order_by('proposal_type')
    )
    review_stats = {
        'pending': all_proposals.filter(status='pending').count(),
        'accepted': all_proposals.filter(status='accepted').count(),
        'rejected': all_proposals.filter(status='rejected').count(),
        'edited': all_proposals.filter(status='edited').count(),
    }

    return render(request, 'reviewer/scan_detail.html', {
        'scan': scan,
        'page_obj': page_obj,
        'proposals': page_obj.object_list,
        'status_filter': status_filter,
        'severity_filter': severity_filter,
        'category_filter': category_filter,
        'categories': categories,
        'can_review': can_review(request.user),
        'review_stats': review_stats,
    })


@reviewer_required
@require_POST
def proposal_action(request, proposal_id, action):
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    if proposal.scan.project_archive and (proposal.scan.created_by_id != request.user.pk and not request.user.is_staff):
        raise Http404('Предложение не найдено.')
    if action == 'accept':
        proposal.status = 'accepted'
    elif action == 'reject':
        proposal.status = 'rejected'
    else:
        raise Http404('Неизвестное действие.')
    proposal.reviewed_by = request.user
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    return redirect('scan_detail', proposal.scan_id)


@reviewer_required
def edit_proposal(request, proposal_id):
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    if proposal.scan.project_archive and (proposal.scan.created_by_id != request.user.pk and not request.user.is_staff):
        raise Http404('Предложение не найдено.')
    if request.method == 'POST':
        proposal.patch_content = request.POST.get('patch_content', proposal.patch_content)
        proposal.after_text = proposal.patch_content
        proposal.reason = request.POST.get('reason', proposal.reason).strip()
        proposal.status = 'edited'
        proposal.reviewed_by = request.user
        proposal.reviewed_at = timezone.now()
        proposal.save(update_fields=[
            'patch_content', 'after_text', 'reason', 'status', 'reviewed_by', 'reviewed_at',
        ])
        messages.success(request, 'Предложение изменено. После проверки его можно принять.')
        return redirect('scan_detail', proposal.scan_id)
    return render(request, 'reviewer/edit_proposal.html', {'proposal': proposal})


def _accepted(scan):
    return list(scan.proposals.filter(status='accepted').order_by('id'))


def _build_patch_text(proposals):
    sections = []
    for proposal in proposals:
        if proposal.before_text and proposal.after_text:
            diff = ''.join(unified_diff(
                proposal.before_text.splitlines(True),
                proposal.after_text.splitlines(True),
                fromfile=f'before/{proposal.drift_id or proposal.id}',
                tofile=f'after/{proposal.drift_id or proposal.id}',
            ))
            if diff:
                sections.append(diff)
                continue
        content = proposal.patch_content or proposal.after_text
        if content:
            header = [
                f'drift_id: {proposal.drift_id or proposal.id}',
                f'endpoint: {proposal.method.upper()} {proposal.path}'.strip(),
                f'category: {proposal.proposal_type}',
                f'target: {proposal.patch_target or "unspecified"}',
                f'type: {proposal.patch_type or "unspecified"}',
                f'location: {proposal.patch_location or proposal.location}',
                '',
                content,
                '',
            ]
            sections.append('\n'.join(header))
    return '\n'.join(sections)


def _download(content, content_type, filename):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_report(request, scan_id, format):
    if format not in {'json', 'md', 'html', 'patch'}:
        raise Http404('Неизвестный формат.')

    scan = get_object_or_404(Scan, pk=scan_id)
    if scan.project_archive and (not request.user.is_authenticated or
                                 (scan.created_by_id != request.user.pk and not request.user.is_staff)):
        raise Http404('Сканирование не найдено.')
    proposals = _accepted(scan)
    base_name = f'scan-{scan.id}'

    if format == 'json':
        data = {
            'scan': scan.name,
            'run_id': scan.run_id,
            'spec_path': scan.spec_path,
            'src_path': scan.source_path,
            'summary': {
                'error': scan.error_count,
                'warning': scan.warning_count,
                'info': scan.info_count,
                'total': scan.drift_count,
            },
            'accepted': [
                {
                    'drift_id': p.drift_id,
                    'endpoint': f'{p.method.upper()} {p.path}'.strip(),
                    'category': p.proposal_type,
                    'severity': p.severity,
                    'location': p.location,
                    'reason': p.reason,
                    'spec_evidence': p.spec_evidence,
                    'code_evidence': p.code_evidence,
                    'source_of_truth': p.source_of_truth,
                    'confidence': p.confidence,
                    'impact': p.impact,
                    'risks': p.risks,
                    'recommendation': p.recommendation,
                    'llm_reasoning': p.llm_reasoning,
                    'patch': {
                        'target': p.patch_target,
                        'patch_type': p.patch_type,
                        'location': p.patch_location,
                        'content': p.patch_content,
                    } if p.patch_content else None,
                    'reviewed_by': p.reviewed_by.username if p.reviewed_by else None,
                    'reviewed_at': p.reviewed_at.isoformat() if p.reviewed_at else None,
                }
                for p in proposals
            ],
        }
        return _download(
            json.dumps(data, ensure_ascii=False, indent=2),
            'application/json; charset=utf-8',
            f'{base_name}.json',
        )

    if format == 'patch':
        return _download(
            _build_patch_text(proposals),
            'text/x-patch; charset=utf-8',
            f'{base_name}.patch',
        )

    if format == 'html':
        html = render_to_string('reviewer/report.html', {'scan': scan, 'proposals': proposals})
        return _download(html, 'text/html; charset=utf-8', f'{base_name}.html')

    chunks = []
    for p in proposals:
        patch_block = p.patch_content or 'Автоматический patch не предоставлен.'
        chunks.append(
            f'## {p.title}\n\n'
            f'- **Drift ID:** `{p.drift_id}`\n'
            f'- **Endpoint:** `{p.method.upper()} {p.path}`\n'
            f'- **Категория:** `{p.proposal_type}`\n'
            f'- **Severity:** `{p.severity}`\n'
            f'- **Location:** `{p.location}`\n'
            f'- **Источник истины:** `{p.source_of_truth or "не указан"}`\n'
            f'- **Уверенность:** `{p.confidence or "не указана"}`\n\n'
            f'**Обоснование:** {p.reason}\n\n'
            f'**Spec evidence:**\n```text\n{p.spec_evidence or "—"}\n```\n\n'
            f'**Code evidence:**\n```text\n{p.code_evidence or "—"}\n```\n\n'
            f'**Patch:**\n```text\n{patch_block}\n```\n'
        )
    md = f'# Отчёт по сканированию: {scan.name}\n\n' + '\n'.join(chunks)
    return _download(md, 'text/markdown; charset=utf-8', f'{base_name}.md')


@require_POST
def create_project_scan(request):
    """Authenticated ZIP upload -> static analysis -> optional LLM -> review DB."""
    from pathlib import Path
    from django.contrib.auth.decorators import login_required
    from django.core.files.base import ContentFile
    from .forms import ProjectScanForm
    from .services.project_analysis import (
        UploadError, analyze, extract_project, file_hash,
        find_openapi, project_workspace, write_report,
    )
    from .services.explanations import MAX_ITEMS, explain_item, fallback

    if not request.user.is_authenticated:
        messages.error(request, 'Для загрузки исходного кода необходимо войти в аккаунт.')
        return redirect('login')
    form = ProjectScanForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, 'reviewer/index.html', {
            'form': ScanForm(), 'project_form': form,
            'scans': visible_scans(request),
        }, status=400)
    upload = form.cleaned_data['project_archive']
    title = form.cleaned_data.get('name') or Path(upload.name).stem
    scan = Scan(name=title, created_by=request.user, scan_status='analyzing')
    scan.project_archive = upload
    spec_upload = form.cleaned_data.get('specification')
    if spec_upload:
        scan.specification = spec_upload
    scan.save()
    workspace = project_workspace(scan.pk)
    try:
        source = extract_project(Path(scan.project_archive.path), workspace / 'source')
        if spec_upload:
            spec_path = Path(scan.specification.path)
        else:
            spec_path = find_openapi(source)
        if not spec_path:
            raise UploadError('OpenAPI не найден в ZIP. Прикрепите отдельный openapi.yaml или openapi.json.')
        scan.archive_sha256 = file_hash(Path(scan.project_archive.path))
        scan.spec_sha256 = file_hash(spec_path)
        items, report = analyze(source, spec_path)
        # Persist the deterministic findings even if external LLM is unavailable.
        scan.scan_status = 'completed'
        write_report(scan, report)
        scan.save()
        import_drift_report(scan, report)
        if form.cleaned_data.get('use_llm') and items:
            provider = form.cleaned_data['llm_provider']
            model = form.cleaned_data['llm_model'] or (
                'llama-3.3-70b-versatile' if provider == 'groq' else 'qwen2.5-coder:7b'
            )
            scan.llm_provider, scan.llm_model, scan.llm_status = provider, model, 'analyzing'
            scan.save(update_fields=['llm_provider', 'llm_model', 'llm_status'])
            # Deterministic scan has already been saved; one model failure must not lose it.
            try:
                from drift_agent.agent import DriftAgent
                from drift_agent.context_tools import ContextToolkit
                agent = DriftAgent(
                    ContextToolkit(source, spec_path), model=model, provider=provider,
                    groq_api_key=(__import__('os').environ.get('GROQ_API_KEY') or __import__('os').environ.get('GROQ_KEY')),
                    ollama_host=__import__('os').environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                )
                enriched = {}
                for item in items[:MAX_ITEMS]:
                    try:
                        result = agent.analyze([item])[0]
                        finding = {
                            'drift_item_id': item.id,
                            'source_of_truth': result.source_of_truth,
                            'confidence': result.confidence,
                            'reasoning': result.reasoning,
                            'patch': result.patch.to_dict() if result.patch else None,
                        }
                        advice = explain_item(item.to_dict(), provider, model)
                        finding.update({
                            'impact': advice['impact'], 'risks': advice['risks'],
                            'recommendation': advice['recommendation'],
                            'llm_reasoning': advice['reasoning'],
                            'llm_confidence': advice['confidence'],
                            'explanation_origin': advice['origin'],
                        })
                        enriched[item.id] = finding
                    except Exception as error:
                        scan.llm_error = f'Не удалось обработать часть находок: {str(error)[:250]}'
                        break
                if enriched:
                    report['findings'] = list(enriched.values())
                    write_report(scan, report)
                    # Update proposals directly; do not duplicate records.
                    for finding in enriched.values():
                        proposal = scan.proposals.filter(drift_id=finding['drift_item_id']).first()
                        if proposal:
                            patch = finding.get('patch') or {}
                            proposal.source_of_truth = finding['source_of_truth']
                            proposal.confidence = finding['confidence']
                            proposal.reason = finding['reasoning']
                            proposal.patch_target = patch.get('target') or ''
                            proposal.patch_type = patch.get('patch_type') or ''
                            proposal.patch_location = patch.get('location') or ''
                            proposal.patch_content = str(patch.get('content') or '')
                            proposal.after_text = proposal.patch_content
                            proposal.impact = finding['impact']
                            proposal.risks = finding['risks']
                            proposal.recommendation = finding['recommendation']
                            proposal.llm_reasoning = finding['llm_reasoning']
                            proposal.llm_confidence = finding['llm_confidence']
                            proposal.explanation_origin = 'llm'
                            proposal.requires_manual_review = (proposal.requires_manual_review or
                                finding['source_of_truth'] == 'AMBIGUOUS' or finding['confidence'] == 'low')
                            proposal.save()
                scan.llm_status = 'completed' if len(enriched) == min(len(items), MAX_ITEMS) else 'partial'
                if len(items) > MAX_ITEMS:
                    scan.llm_error = f'LLM обработала только первые {MAX_ITEMS} находок (лимит MVP).'
            except Exception as exc:
                scan.llm_status = 'unavailable'
                scan.llm_error = str(exc)[:1200]
            finally:
                scan.save()
        messages.success(request, f'Проект обработан: {len(items)} расхождений. Результат сохранён.')
        if scan.llm_error:
            messages.warning(request, f'LLM: {scan.llm_error}')
    except Exception as error:
        scan.scan_status = 'failed'
        scan.analysis_error = str(error)[:2000]
        scan.save(update_fields=['scan_status', 'analysis_error'])
        messages.error(request, f'Анализ не выполнен: {scan.analysis_error}')
    return redirect('scan_detail', scan.pk)



def scan_download(request, scan_id, artifact):
    scan = get_object_or_404(Scan, pk=scan_id)
    if not request.user.is_authenticated or (scan.created_by_id != request.user.pk and not request.user.is_staff):
        raise Http404('Файл не найден.')
    field = {'zip': scan.project_archive, 'openapi': scan.specification, 'json': scan.drift_report}.get(artifact)
    if not field or not field.name:
        raise Http404('Файл не найден.')
    from pathlib import Path
    filename = Path(field.name).name
    return FileResponse(field.open('rb'), as_attachment=True, filename=filename,
                        content_type='application/octet-stream')
