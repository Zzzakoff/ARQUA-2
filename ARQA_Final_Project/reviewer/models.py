from django.conf import settings
from django.db import models


class Scan(models.Model):
    name = models.CharField(max_length=200)
    specification = models.FileField(upload_to='specifications/', blank=True)
    drift_report = models.FileField(upload_to='drift_reports/', blank=True)
    project_archive = models.FileField(upload_to='private_projects/archives/', blank=True)
    spec_sha256 = models.CharField(max_length=64, blank=True)
    archive_sha256 = models.CharField(max_length=64, blank=True)
    scan_status = models.CharField(max_length=20, default='completed')
    analysis_error = models.TextField(blank=True)
    llm_provider = models.CharField(max_length=20, blank=True)
    llm_model = models.CharField(max_length=120, blank=True)
    llm_status = models.CharField(max_length=30, blank=True)
    llm_error = models.TextField(blank=True)
    run_id = models.CharField(max_length=64, blank=True)
    spec_path = models.CharField(max_length=500, blank=True)
    source_path = models.CharField(max_length=500, blank=True)
    spec_endpoints = models.PositiveIntegerField(default=0)
    code_endpoints = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    info_count = models.PositiveIntegerField(default=0)
    drift_count = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='children',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='scans',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} v{self.version}'


class Proposal(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('accepted', 'Принято'),
        ('rejected', 'Отклонено'),
        ('edited', 'Изменено'),
    ]
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name='proposals')
    drift_id = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=300)
    path = models.CharField(max_length=500)
    method = models.CharField(max_length=20, blank=True)
    proposal_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=500, blank=True)
    reason = models.TextField()
    spec_evidence = models.TextField(blank=True)
    code_evidence = models.TextField(blank=True)
    source_of_truth = models.CharField(max_length=100, blank=True)
    confidence = models.CharField(max_length=30, blank=True)
    patch_target = models.CharField(max_length=30, blank=True)
    patch_type = models.CharField(max_length=100, blank=True)
    patch_location = models.CharField(max_length=500, blank=True)
    patch_content = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    before_text = models.TextField(blank=True)
    after_text = models.TextField(blank=True)
    manual_analytics = models.TextField(blank=True)
    requires_manual_review = models.BooleanField(default=False)
    taxonomy = models.CharField(max_length=80, blank=True)
    priority = models.CharField(max_length=10, blank=True)
    source_file = models.CharField(max_length=500, blank=True)
    source_line = models.PositiveIntegerField(null=True, blank=True)
    impact = models.TextField(blank=True)
    risks = models.TextField(blank=True)
    recommendation = models.CharField(max_length=30, blank=True)
    llm_reasoning = models.TextField(blank=True)
    llm_confidence = models.CharField(max_length=30, blank=True)
    explanation_origin = models.CharField(max_length=20, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_proposals',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
