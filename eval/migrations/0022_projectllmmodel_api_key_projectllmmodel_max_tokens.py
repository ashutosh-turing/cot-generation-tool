# Generated by Django 5.2 on 2025-07-24 14:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0021_llmmodel_is_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectllmmodel',
            name='api_key',
            field=models.CharField(blank=True, help_text='Override API key for this project (optional)', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='projectllmmodel',
            name='max_tokens',
            field=models.PositiveIntegerField(blank=True, help_text='Override max tokens for this project (optional)', null=True),
        ),
    ]
