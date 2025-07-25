# Generated by Django 4.2.20 on 2025-04-08 11:58

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('eval', '0002_validation_description_validation_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='validation',
            name='username',
        ),
        migrations.AddField(
            model_name='validation',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='validation',
            name='name',
            field=models.CharField(max_length=200),
        ),
        migrations.CreateModel(
            name='ModelEvaluationHistory',
            fields=[
                ('evaluation_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('model_name', models.CharField(max_length=100)),
                ('prompt', models.TextField()),
                ('system_instructions', models.TextField(blank=True)),
                ('temperature', models.FloatField(default=0.7)),
                ('max_tokens', models.IntegerField(default=2048)),
                ('evaluation_metrics', models.JSONField(default=dict)),
                ('response', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('username', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
