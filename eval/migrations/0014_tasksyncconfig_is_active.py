# Generated migration for adding is_active field to TaskSyncConfig

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0013_alter_llmmodel_provider_llmjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='tasksyncconfig',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Whether this sync configuration is active'),
        ),
    ]
