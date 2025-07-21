import os
import sys
import time
import django
from datetime import timedelta
from django.utils import timezone

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coreproject.settings")
django.setup()

from eval.models import TaskSyncConfig
from eval.utils.sheets import sync_trainer_tasks

def run_sync_loop():
    print("Starting TaskSyncConfig auto-sync daemon...")
    while True:
        now = timezone.now()
        print(f"[{now}] Daemon heartbeat: checking TaskSyncConfig...")
        configs = TaskSyncConfig.objects.all()
        for config in configs:
            # If never synced, or enough time has passed since last_synced
            if (
                not config.last_synced or
                (now - config.last_synced) >= timedelta(minutes=config.sync_interval_minutes)
            ):
                print(f"[{now}] Syncing config: {config.sheet_url}")
                try:
                    status, summary, details, created, updated, deleted = sync_trainer_tasks(
                        config,
                        selected_project=config.project,
                        sync_type="auto",
                        synced_by="system"
                    )
                    print(f"[{now}] Status: {status}, Summary: {summary}")
                    if details:
                        print(f"[{now}] Details: {details}")
                except Exception as e:
                    print(f"[{now}] Error syncing {config.sheet_url}: {e}")
            else:
                print(f"[{now}] Skipping config: {config.sheet_url} (last synced {config.last_synced})")
        # Sleep for 1 minute before checking again
        time.sleep(60)

if __name__ == "__main__":
    run_sync_loop()
