#!/usr/bin/env python3
"""
Sync Daemon Monitor - Monitor the status of sync configurations and daemon performance
"""

import os
import sys
import django
from datetime import timedelta
from django.utils import timezone

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coreproject.settings")
django.setup()

from eval.models import TaskSyncConfig, TaskSyncHistory, Project

def print_separator(title=""):
    print("=" * 80)
    if title:
        print(f" {title} ".center(80, "="))
        print("=" * 80)

def format_duration(td):
    """Format timedelta in a human-readable way"""
    if td is None:
        return "Never"
    
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def get_sync_status():
    """Get comprehensive sync status for all configurations"""
    print_separator("SYNC DAEMON STATUS MONITOR")
    
    now = timezone.now()
    configs = TaskSyncConfig.objects.all().order_by('id')
    
    print(f"Timestamp: {now}")
    print(f"Total Configurations: {configs.count()}")
    print()
    
    for config in configs:
        project_name = config.project.code if config.project else "No Project"
        print(f"┌─ Config {config.id}: {project_name}")
        print(f"│  Sheet URL: {config.sheet_url}")
        print(f"│  Sync Interval: {config.sync_interval_minutes} minutes")
        print(f"│  Active: {'✓' if config.is_active else '✗'}")
        
        if config.last_synced:
            time_since_sync = now - config.last_synced
            minutes_since = time_since_sync.total_seconds() / 60
            should_sync = minutes_since >= config.sync_interval_minutes
            
            print(f"│  Last Synced: {config.last_synced} ({format_duration(time_since_sync)} ago)")
            print(f"│  Should Sync Now: {'✓ YES' if should_sync else '✗ No'}")
            
            # Calculate next sync time
            next_sync = config.last_synced + timedelta(minutes=config.sync_interval_minutes)
            time_to_next = next_sync - now
            if time_to_next.total_seconds() > 0:
                print(f"│  Next Sync In: {format_duration(time_to_next)}")
            else:
                print(f"│  Next Sync: Overdue by {format_duration(-time_to_next)}")
        else:
            print(f"│  Last Synced: Never")
            print(f"│  Should Sync Now: ✓ YES (First sync)")
        
        print("└─")
        print()

def get_recent_sync_history(limit=10):
    """Show recent sync history across all configurations"""
    print_separator("RECENT SYNC HISTORY")
    
    history = TaskSyncHistory.objects.all().order_by('-timestamp')[:limit]
    
    if not history:
        print("No sync history found.")
        return
    
    print(f"Showing last {min(limit, history.count())} sync operations:")
    print()
    
    for h in history:
        project_name = h.config.project.code if h.config.project else "No Project"
        status_icon = "✓" if h.status == "success" else "✗"
        
        print(f"{h.timestamp} | Config {h.config.id} ({project_name})")
        print(f"  {status_icon} {h.status.upper()} | {h.sync_type} | {h.summary}")
        if h.details and h.status == "failure":
            # Show first line of error details
            first_line = h.details.split('\n')[0]
            print(f"  Error: {first_line}")
        print()

def get_sync_performance():
    """Analyze sync performance and patterns"""
    print_separator("SYNC PERFORMANCE ANALYSIS")
    
    # Get sync history for the last 24 hours
    since = timezone.now() - timedelta(hours=24)
    recent_history = TaskSyncHistory.objects.filter(timestamp__gte=since)
    
    print(f"Analysis for last 24 hours (since {since}):")
    print()
    
    # Overall stats
    total_syncs = recent_history.count()
    successful_syncs = recent_history.filter(status='success').count()
    failed_syncs = recent_history.filter(status='failure').count()
    
    success_rate = (successful_syncs / total_syncs * 100) if total_syncs > 0 else 0
    
    print(f"Total Syncs: {total_syncs}")
    print(f"Successful: {successful_syncs}")
    print(f"Failed: {failed_syncs}")
    print(f"Success Rate: {success_rate:.1f}%")
    print()
    
    # Per-config breakdown
    configs = TaskSyncConfig.objects.all()
    for config in configs:
        project_name = config.project.code if config.project else "No Project"
        config_history = recent_history.filter(config=config)
        config_total = config_history.count()
        config_success = config_history.filter(status='success').count()
        
        if config_total > 0:
            config_rate = (config_success / config_total * 100)
            print(f"Config {config.id} ({project_name}): {config_success}/{config_total} ({config_rate:.1f}%)")
        else:
            print(f"Config {config.id} ({project_name}): No syncs in last 24h")

def check_daemon_health():
    """Check if daemon appears to be running correctly"""
    print_separator("DAEMON HEALTH CHECK")
    
    now = timezone.now()
    
    # Check if any configs are overdue for sync
    overdue_configs = []
    for config in TaskSyncConfig.objects.filter(is_active=True):
        if config.last_synced:
            time_since_sync = now - config.last_synced
            if time_since_sync >= timedelta(minutes=config.sync_interval_minutes * 2):  # 2x interval = concerning
                overdue_configs.append((config, time_since_sync))
        else:
            # Never synced configs are also concerning if they've existed for a while
            if config.created_at < now - timedelta(minutes=10):
                overdue_configs.append((config, None))
    
    if overdue_configs:
        print("⚠️  WARNING: Some configurations appear overdue for sync:")
        for config, overdue_time in overdue_configs:
            project_name = config.project.code if config.project else "No Project"
            if overdue_time:
                print(f"  - Config {config.id} ({project_name}): {format_duration(overdue_time)} overdue")
            else:
                print(f"  - Config {config.id} ({project_name}): Never synced")
        print()
        print("This might indicate the sync daemon is not running or has issues.")
    else:
        print("✓ All active configurations appear to be syncing on schedule.")
    
    print()
    
    # Check for recent failures
    recent_failures = TaskSyncHistory.objects.filter(
        timestamp__gte=now - timedelta(hours=1),
        status='failure'
    )
    
    if recent_failures.exists():
        print(f"⚠️  WARNING: {recent_failures.count()} sync failures in the last hour:")
        for failure in recent_failures[:3]:  # Show first 3
            project_name = failure.config.project.code if failure.config.project else "No Project"
            print(f"  - Config {failure.config.id} ({project_name}): {failure.summary}")
        if recent_failures.count() > 3:
            print(f"  ... and {recent_failures.count() - 3} more")
    else:
        print("✓ No sync failures in the last hour.")

def main():
    """Main monitoring function"""
    try:
        get_sync_status()
        get_recent_sync_history()
        get_sync_performance()
        check_daemon_health()
        
        print_separator("MONITORING COMPLETE")
        print("To run this monitor continuously, you can use:")
        print("  watch -n 30 python sync_daemon_monitor.py")
        print()
        print("To view live daemon logs:")
        print("  tail -f sync_daemon.log")
        
    except Exception as e:
        print(f"Error running monitor: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
