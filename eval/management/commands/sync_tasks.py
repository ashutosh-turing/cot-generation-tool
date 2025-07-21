from django.core.management.base import BaseCommand
from eval.models import TaskSyncConfig
from eval.utils.sheets import sync_trainer_tasks
from django.utils import timezone
from datetime import timedelta

class Command(BaseCommand):
    help = "Auto-sync TrainerTask from Google Sheets based on TaskSyncConfig intervals."

    def handle(self, *args, **options):
        now = timezone.now()
        configs = TaskSyncConfig.objects.all()
        for config in configs:
            # If never synced, or enough time has passed since last_synced
            if (
                not config.last_synced or
                (now - config.last_synced) >= timedelta(minutes=config.sync_interval_minutes)
            ):
                self.stdout.write(f"Syncing config: {config.sheet_url}")
                status, summary, details, created, updated, deleted = sync_trainer_tasks(
                    config,
                    selected_project=config.project,
                    sync_type="auto",
                    synced_by="system"
                )
                self.stdout.write(f"Status: {status}, Summary: {summary}")
                if details:
                    self.stdout.write(f"Details: {details}")
            else:
                self.stdout.write(f"Skipping config: {config.sheet_url} (last synced {config.last_synced})")
