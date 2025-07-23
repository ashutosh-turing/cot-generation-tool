#!/bin/bash

# Dry Run Deployment Script for Django eval project V2
# This script checks and reports what would change in a real deployment,
# but does NOT make any changes to code, database, or services.

set -e

PROJECT_DIR="/home/cot-generation-tool"
DB_PATH="$PROJECT_DIR/db_v2.sqlite3"
BACKUP_DIR="$PROJECT_DIR/db_backups_v2"
COMMIT_FILE="$PROJECT_DIR/last_deploy_commit_v2.txt"
VENV_DIR="$PROJECT_DIR/venv"
GUNICORN_SOCK="$PROJECT_DIR/gunicorn_v2.sock"
GUNICORN_PID="$PROJECT_DIR/gunicorn_v2.pid"
AUTO_PROCESSOR_PID="$PROJECT_DIR/auto_processor_v2.pid"

echo "==== DRY RUN: Enhanced V2 Deployment Preview ===="

cd "$PROJECT_DIR"

# 1. Check for new commits on main branch
echo ""
echo "Checking for new commits on main branch..."
git fetch origin main
LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main)
if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
    echo "→ New commits are available on main branch."
    echo "  Local HEAD:  $LOCAL_COMMIT"
    echo "  Remote HEAD: $REMOTE_COMMIT"
    echo "  Would pull latest code in real deployment."
else
    echo "✓ Local code is up to date with main branch."
fi

# 2. Check if requirements.txt has changed
echo ""
echo "Checking if requirements.txt has changed in remote..."
if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
    git diff --name-status "$LOCAL_COMMIT" "$REMOTE_COMMIT" | grep requirements.txt > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "→ requirements.txt has changed between local and remote."
        echo "  Would install updated dependencies in real deployment."
    else
        echo "✓ requirements.txt has not changed."
    fi
else
    echo "✓ requirements.txt is up to date."
fi

# 3. Check for new migration files (unapplied migrations)
echo ""
echo "Checking for unapplied Django migrations..."
source "$VENV_DIR/bin/activate"
export DJANGO_SETTINGS_MODULE=coreproject.settings
UNAPPLIED=$(python3 manage.py showmigrations --plan | grep '\[ \]' || true)
if [ -n "$UNAPPLIED" ]; then
    echo "→ There are unapplied migrations:"
    echo "$UNAPPLIED"
    echo "  Would apply these migrations in a real deployment (but NOT in this dry run)."
else
    echo "✓ All migrations are applied. No schema changes pending."
fi

# 4. Check status of critical services
echo ""
echo "Checking status of critical services..."
if [ -f "$GUNICORN_PID" ] && kill -0 "$(cat $GUNICORN_PID)" 2>/dev/null; then
    echo "✓ Gunicorn: RUNNING (PID: $(cat $GUNICORN_PID))"
else
    echo "⚠ Gunicorn: NOT RUNNING"
fi

if systemctl is-active --quiet llm-job-processor.service 2>/dev/null; then
    echo "✓ Auto Processor: RUNNING (systemd service)"
elif [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
    echo "✓ Auto Processor: RUNNING (PID: $(cat $AUTO_PROCESSOR_PID))"
else
    echo "⚠ Auto Processor: NOT RUNNING"
fi

if pgrep -f "process_llm_jobs" > /dev/null; then
    WORKER_PID=$(pgrep -f "process_llm_jobs")
    echo "✓ Pub/Sub Worker: RUNNING (PID: $WORKER_PID)"
else
    echo "⚠ Pub/Sub Worker: NOT RUNNING"
fi

if pgrep -f "run_sync_daemon" > /dev/null; then
    DAEMON_PID=$(pgrep -f "run_sync_daemon")
    echo "✓ Sync Daemon: RUNNING (PID: $DAEMON_PID)"
else
    echo "⚠ Sync Daemon: NOT RUNNING"
fi

# 5. Summary of what would happen in a real deployment
echo ""
echo "==== DRY RUN SUMMARY ===="
if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
    echo "• Would pull latest code from main branch."
else
    echo "• Code is up to date. No git pull needed."
fi

if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
    git diff --name-status "$LOCAL_COMMIT" "$REMOTE_COMMIT" | grep requirements.txt > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "• Would install updated Python dependencies."
    fi
fi

if [ -n "$UNAPPLIED" ]; then
    echo "• Would apply unapplied Django migrations (but NOT in this dry run)."
else
    echo "• No migrations to apply."
fi

echo "• Would restart Gunicorn, auto processor, pub/sub worker, and sync daemon as needed."
echo ""
echo "==== END OF DRY RUN ===="
echo "No changes have been made to the system."
