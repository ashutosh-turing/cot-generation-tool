# Generated by Django 5.2 on 2025-07-18 07:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0011_tasksyncconfig_project'),
    ]

    operations = [
        migrations.CreateModel(
            name='LLMModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('provider', models.CharField(choices=[('openai', 'OpenAI'), ('anthropic', 'Anthropic'), ('gemini', 'Google Gemini'), ('deepseek', 'DeepSeek')], default='openai', max_length=20)),
                ('api_key', models.CharField(blank=True, help_text="API key for this model's provider. If blank, will use environment variable.", max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                ('temperature', models.FloatField(default=0.7)),
                ('is_active', models.BooleanField(default=True)),
            ],
        ),
    ]
