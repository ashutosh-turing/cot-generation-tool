# Generated by Django 5.2 on 2025-07-25 14:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0022_projectllmmodel_api_key_projectllmmodel_max_tokens'),
    ]

    operations = [
        migrations.AddField(
            model_name='llmmodel',
            name='use_streaming',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='projectllmmodel',
            name='use_streaming',
            field=models.BooleanField(default=True),
        ),
    ]
