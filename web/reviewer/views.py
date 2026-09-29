import json
from difflib import unified_diff

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import can_review, reviewer_required
from .forms import ScanForm
from .models import Proposal, Scan
from patch_engine.proposals import generate_response_proposal


def index(request):
    if request.method == 'POST':
        form = ScanForm(request.POST, request.FILES)
        if form.is_valid():
            scan = form.save(commit=False)
            if request.user.is_authenticated:
                scan.created_by = request.user
            scan.save()
            messages.success(request, f'Скан «{scan.name}» создан.')
            return redirect('scan_detail', scan.id)
        for field, errors in form.errors.items():
            for err in errors:
                messages.error(request, f'{field}: {err}')
        return render(request, 'reviewer/index.html', {
            'form': form,
            'scans': Scan.objects.order_by('-created_at'),
        })

    return render(request, 'reviewer/index.html', {
        'form': ScanForm(),
        'scans': Scan.objects.order_by('-created_at'),
    })


def scan_detail(request, scan_id):
    scan = get_object_or_404(Scan, pk=scan_id)

    if request.method == 'POST':
        if not can_review(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Требуется роль reviewer.')

        path = request.POST.get('path', '').strip()
        method = request.POST.get('method', 'get').lower()
        status = request.POST.get('status_code', '404').strip()
        description = request.POST.get('description', '').strip()
        try:
            with scan.specification.open('rb') as fh:
                spec_text = fh.read().decode('utf-8')
            proposal = generate_response_proposal(
                spec_text, path, method, status, description
            )
            Proposal.objects.create(
                scan=scan,
                title=proposal['title'],
                path=proposal['path'],
                method=proposal['method'],
                proposal_type=proposal['proposal_type'],
                reason=proposal['reason'],
                source_of_truth=proposal['source_of_truth'],
                confidence=proposal['confidence'],
                before_text=proposal['before'],
                after_text=proposal['after'],
                manual_analytics=proposal['manual_analytics'],
                requires_manual_review=proposal.get('requires_manual_review', False),
            )
            messages.success(request, 'Patch proposal создан.')
        except Exception as exc:
            messages.error(request, f'Ошибка генерации: {exc}')
        return redirect('scan_detail', scan.id)

    qs = scan.proposals.order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter in {'pending', 'accepted', 'rejected', 'edited'}:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    all_proposals = scan.proposals.all()
    stats = {
        'total': all_proposals.count(),
        'pending': all_proposals.filter(status='pending').count(),
        'accepted': all_proposals.filter(status='accepted').count(),
        'rejected': all_proposals.filter(status='rejected').count(),
        'edited': all_proposals.filter(status='edited').count(),
    }

    return render(request, 'reviewer/scan_detail.html', {
        'scan': scan,
        'page_obj': page_obj,
        'proposals': page_obj.object_list,
        'status_filter': status_filter or '',
        'can_review': can_review(request.user),
        'stats': stats,
    })


@reviewer_required
@require_POST
def proposal_action(request, proposal_id, action):
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    if action == 'accept':
        proposal.status = 'accepted'
    elif action == 'reject':
        proposal.status = 'rejected'
    else:
        return redirect('scan_detail', proposal.scan_id)

    proposal.reviewed_by = request.user
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    return redirect('scan_detail', proposal.scan_id)


@reviewer_required
def edit_proposal(request, proposal_id):
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    if request.method == 'POST':
        proposal.after_text = request.POST.get('after_text', proposal.after_text)
        proposal.status = 'edited'
        proposal.reviewed_by = request.user
        proposal.reviewed_at = timezone.now()
        proposal.save(update_fields=['after_text', 'status', 'reviewed_by', 'reviewed_at'])
        messages.success(request, 'Предложение изменено. Проверьте результат и нажмите «Принять», чтобы включить его в экспорт.')
        return redirect('scan_detail', proposal.scan_id)
    return render(request, 'reviewer/edit_proposal.html', {'proposal': proposal})


def _build_patch_chunks(proposals):
    chunks = []
    for p in proposals:
        diff = ''.join(unified_diff(
            p.before_text.splitlines(True),
            p.after_text.splitlines(True),
            fromfile='a/openapi.yaml',
            tofile='b/openapi.yaml',
        ))
        chunks.append(diff)
    return ''.join(chunks)


def export_report(request, scan_id, format):
    if format not in {'json', 'md', 'html', 'patch'}:
        raise Http404('Неизвестный формат отчёта.')

    scan = get_object_or_404(Scan, pk=scan_id)
    proposals = list(scan.proposals.filter(status='accepted').order_by('id'))

    if format == 'json':
        data = {
            'scan': scan.name,
            'created_at': scan.created_at.isoformat(),
            'proposals': [
                {
                    'title': p.title, 'path': p.path, 'method': p.method,
                    'proposal_type': p.proposal_type,
                    'status': p.status, 'reason': p.reason,
                    'source_of_truth': p.source_of_truth,
                    'confidence': p.confidence,
                    'before': p.before_text, 'after': p.after_text,
                    'manual_analytics': p.manual_analytics,
                    'reviewed_by': p.reviewed_by.username if p.reviewed_by else None,
                    'reviewed_at': p.reviewed_at.isoformat() if p.reviewed_at else None,
                }
                for p in proposals
            ],
        }
        response = HttpResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8',
        )
        response['Content-Disposition'] = f'attachment; filename="scan-{scan.id}-report.json"'
        return response

    if format == 'patch':
        response = HttpResponse(
            _build_patch_chunks(proposals),
            content_type='text/x-patch; charset=utf-8',
        )
        response['Content-Disposition'] = f'attachment; filename="scan-{scan.id}.patch"'
        return response

    if format == 'html':
        html = render_to_string('reviewer/report.html', {
            'scan': scan,
            'proposals': proposals,
        })
        response = HttpResponse(html, content_type='text/html; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="scan-{scan.id}-report.html"'
        return response

    chunks = []
    for p in proposals:
        diff = ''.join(unified_diff(
            p.before_text.splitlines(True),
            p.after_text.splitlines(True),
            fromfile='before/openapi.yaml',
            tofile='after/openapi.yaml',
        ))
        chunks.append(
            f'## {p.title}\n\n'
            f'- **Path:** `{p.path}`\n'
            f'- **Метод:** `{p.method}`\n'
            f'- **Тип:** {p.proposal_type}\n'
            f'- **Источник истины:** {p.source_of_truth}\n'
            f'- **Уверенность:** {p.confidence}\n\n'
            f'**Причина:** {p.reason}\n\n'
            f'```diff\n{diff}\n```\n'
        )
    md = f'# Отчёт по сканированию: {scan.name}\n\n' + '\n'.join(chunks)
    response = HttpResponse(md, content_type='text/markdown; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="scan-{scan.id}-report.md"'
    return response
