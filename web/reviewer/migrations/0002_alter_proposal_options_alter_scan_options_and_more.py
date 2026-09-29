
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewer', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='proposal',
            options={'ordering': ['-created_at']},
        ),
        migrations.AlterModelOptions(
            name='scan',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddField(
            model_name='proposal',
            name='requires_manual_review',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='proposal',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='proposal',
            name='reviewed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_proposals', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='scan',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scans', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='scan',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='children', to='reviewer.scan'),
        ),
        migrations.AddField(
            model_name='scan',
            name='version',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
