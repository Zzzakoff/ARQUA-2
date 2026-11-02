
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Scan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('specification', models.FileField(upload_to='specifications/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Proposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300)),
                ('path', models.CharField(max_length=500)),
                ('method', models.CharField(blank=True, max_length=20)),
                ('proposal_type', models.CharField(max_length=100)),
                ('reason', models.TextField()),
                ('source_of_truth', models.CharField(max_length=100)),
                ('confidence', models.CharField(max_length=30)),
                ('status', models.CharField(choices=[('pending', 'Ожидает'), ('accepted', 'Принято'), ('rejected', 'Отклонено'), ('edited', 'Изменено')], default='pending', max_length=20)),
                ('before_text', models.TextField()),
                ('after_text', models.TextField()),
                ('manual_analytics', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('scan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proposals', to='reviewer.scan')),
            ],
        ),
    ]
