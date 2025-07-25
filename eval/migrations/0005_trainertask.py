# Generated by Django 5.2 on 2025-07-16 14:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0004_modelevaluationhistory_edit_history_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrainerTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reviewer', models.CharField(blank=True, max_length=255, null=True)),
                ('developer', models.CharField(blank=True, max_length=255, null=True)),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('raw_prompt', models.TextField(blank=True, null=True)),
                ('response_links', models.TextField(blank=True, null=True)),
                ('rating', models.CharField(blank=True, max_length=50, null=True)),
                ('level_of_difficulty', models.CharField(blank=True, max_length=50, null=True)),
                ('question_id', models.CharField(blank=True, max_length=100, null=True)),
                ('problem_link', models.URLField(blank=True, null=True)),
                ('labelling_tool_id_link', models.CharField(blank=True, max_length=255, null=True)),
                ('completed', models.CharField(blank=True, max_length=50, null=True)),
                ('count', models.CharField(blank=True, max_length=50, null=True)),
                ('delivered', models.CharField(blank=True, max_length=50, null=True)),
                ('screenshot_drive_link', models.CharField(blank=True, max_length=255, null=True)),
                ('exported_batch', models.CharField(blank=True, max_length=255, null=True)),
                ('codeforces_submission_id', models.CharField(blank=True, max_length=255, null=True)),
                ('plagiarism', models.CharField(blank=True, max_length=255, null=True)),
                ('review_doc', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
