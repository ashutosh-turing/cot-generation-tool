import json
import os

from django.core.management.base import BaseCommand, CommandError
from eval.models import TaskSyncConfig, Project

class Command(BaseCommand):
    help = "Import TaskSyncConfig from a JSON file (default: example_config.json)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='example_config.json',
            help='Path to the config JSON file (default: example_config.json)'
        )

    def handle(self, *args, **options):
        config_path = options['file']
        if not os.path.exists(config_path):
            raise CommandError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            data = json.load(f)

        project_code = data.get('project_code')
        if not project_code:
            raise CommandError("project_code is required in config JSON.")

        # Find the Project by code
        try:
            project = Project.objects.get(code=project_code)
        except Project.DoesNotExist:
            raise CommandError(f"Project with code '{project_code}' does not exist. Please create it first.")

        # Find or create TaskSyncConfig by project
        config, created = TaskSyncConfig.objects.get_or_create(project=project)

        # Set fields from JSON
        config.sheet_url = data.get('sheet_url')
        config.sync_interval_minutes = data.get('sync_interval_minutes')
        config.primary_key_column = data.get('primary_key_column')
        config.scraping_needed = data.get('scraping_needed', False)
        config.link_column = data.get('link_column')
        config.column_mapping = data.get('column_mapping')
        config.field_types = data.get('field_types')
        config.display_config = data.get('display_config')
        config.sync_mode = data.get('sync_mode')
        config.sheet_tab = data.get('sheet_tab')
        config.is_active = data.get('is_active', True)

        config.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created TaskSyncConfig for project_code: {project_code}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated TaskSyncConfig for project_code: {project_code}"))
