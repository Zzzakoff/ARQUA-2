from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewer', '0002_alter_proposal_options_alter_scan_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scan',
            name='specification',
            field=models.FileField(blank=True, upload_to='specifications/'),
        ),
        migrations.AddField(model_name='scan', name='drift_report', field=models.FileField(blank=True, upload_to='drift_reports/')),
        migrations.AddField(model_name='scan', name='run_id', field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name='scan', name='spec_path', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='scan', name='source_path', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='scan', name='spec_endpoints', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='scan', name='code_endpoints', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='scan', name='error_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='scan', name='warning_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='scan', name='info_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='scan', name='drift_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='proposal', name='drift_id', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='proposal', name='severity', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='proposal', name='location', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='proposal', name='spec_evidence', field=models.TextField(blank=True)),
        migrations.AddField(model_name='proposal', name='code_evidence', field=models.TextField(blank=True)),
        migrations.AddField(model_name='proposal', name='patch_target', field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name='proposal', name='patch_type', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='proposal', name='patch_location', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='proposal', name='patch_content', field=models.TextField(blank=True)),
        migrations.AlterField(model_name='proposal', name='source_of_truth', field=models.CharField(blank=True, max_length=100)),
        migrations.AlterField(model_name='proposal', name='confidence', field=models.CharField(blank=True, max_length=30)),
        migrations.AlterField(model_name='proposal', name='before_text', field=models.TextField(blank=True)),
        migrations.AlterField(model_name='proposal', name='after_text', field=models.TextField(blank=True)),
    ]
