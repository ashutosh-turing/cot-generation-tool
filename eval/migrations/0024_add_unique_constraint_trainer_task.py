# Generated manually to add unique constraint for TrainerTask

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0023_llmmodel_use_streaming_projectllmmodel_use_streaming'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='trainertask',
            constraint=models.UniqueConstraint(
                fields=['question_id', 'project'],
                name='unique_question_id_per_project',
                condition=models.Q(question_id__isnull=False)
            ),
        ),
    ]
