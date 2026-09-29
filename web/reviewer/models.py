from django.conf import settings
from django.db import models


class Scan(models.Model):
    name = models.CharField(max_length=200)
    specification = models.FileField(upload_to='specifications/')
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
    title = models.CharField(max_length=300)
    path = models.CharField(max_length=500)
    method = models.CharField(max_length=20, blank=True)
    proposal_type = models.CharField(max_length=100)
    reason = models.TextField()
    source_of_truth = models.CharField(max_length=100)
    confidence = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    before_text = models.TextField()
    after_text = models.TextField()
    manual_analytics = models.TextField(blank=True)
    requires_manual_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_proposals',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
