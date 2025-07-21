#!/bin/bash

# Deployment and rollback script for Django eval project V2 (LOCALIZED VERSION)
# Usage:
#   ./deploy.sh deploy    # Deploy latest version
#   ./deploy.sh rollback # Rollback to previous version
#   ./deploy.sh local    # Run local dev server

set -e

# Localized V2 Configuration
PROJECT_DIR="/home/cot-generation-tool"
DB_PATH="$PROJECT_DIR/db_v2.sqlite3"
BACKUP_DIR="$PROJECT_DIR/db_backups_v2"
COMMIT_FILE="$PROJECT_DIR/last_deploy_commit_v2.txt"
LOG_FILE="$PROJECT_DIR/logs/deploy_v2.log"
VENV_DIR="$PROJECT_DIR/venv"
GUNICORN_SOCK="$PROJECT_DIR/gunicorn_v2.sock"
GUNICORN_PID="$PROJECT_DIR/gunicorn_v2.pid"

log() {
    mkdir -p "$PROJECT_DIR/logs"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup_gunicorn_socket() {
    if [ -S "$GUNICORN_SOCK" ]; then
        log "Removing stale gunicorn socket $GUNICORN_SOCK"
        rm -f "$GUNICORN_SOCK"
    fi
}

stop_gunicorn() {
    if [ -f "$GUNICORN_PID" ]; then
        log "Stopping Gunicorn via PID file..."
        kill "$(cat $GUNICORN_PID)" || true
        rm -f "$GUNICORN_PID"
    else
        log "Stopping Gunicorn via pkill fallback..."
        pkill -f "gunicorn.*v2" || true
    fi
}

deploy() {
    log "=== Starting V2 deployment ==="

    source "$VENV_DIR/bin/activate"

    # 1. Backup database
    log "Backing up V2 database..."
    mkdir -p "$BACKUP_DIR"
    if [ -f "$DB_PATH" ]; then
        cp "$DB_PATH" "$BACKUP_DIR/db_v2_backup_$(date +%Y%m%d_%H%M%S).sqlite3"
    fi

    # 2. Save current commit hash
    cd "$PROJECT_DIR"
    CURRENT_COMMIT=$(git rev-parse HEAD)
    echo "$CURRENT_COMMIT" > "$COMMIT_FILE"
    log "Saved current commit hash: $CURRENT_COMMIT"

    # 3. Pull latest code from main branch
    log "Pulling latest code from main branch..."
    git pull origin main

    # 4. Install dependencies
    log "Installing Python dependencies..."
    pip install -r requirements.txt

    # 5. Run migrations
    log "Running Django migrations..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py migrate --noinput

    # 6. Collect static files
    log "Collecting static files..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py collectstatic --noinput

    # 7. Stop old V2 services
    log "Stopping old V2 services..."
    stop_gunicorn
    pkill -f "process_llm_jobs.*v2" || true
    pkill -f "run_sync_daemon.*v2" || true

    cleanup_gunicorn_socket

    # 8. Start Gunicorn V2
    log "Starting Gunicorn V2..."
    gunicorn coreproject.wsgi:application \
        --workers 3 \
        --bind unix:"$GUNICORN_SOCK" \
        --timeout 300 \
        --daemon \
        --pid "$GUNICORN_PID" \
        --access-logfile "$PROJECT_DIR/logs/v2_access.log" \
        --error-logfile "$PROJECT_DIR/logs/v2_error.log"

    sleep 2
    if [ ! -S "$GUNICORN_SOCK" ]; then
        log "ERROR: Gunicorn socket $GUNICORN_SOCK was not created!"
        exit 1
    fi

    # 9. Start background services for V2
    log "Starting background services for V2..."
    nohup python3 manage.py process_llm_jobs > logs/llm_jobs_v2.log 2>&1 &
    nohup python3 run_sync_daemon.py > logs/sync_daemon_v2.log 2>&1 &
    
    # Verify services are running
    sleep 3
    if pgrep -f "process_llm_jobs" > /dev/null; then
        log "✓ LLM job processing service is running"
    else
        log "⚠ WARNING: LLM job processing service may not be running"
    fi
    
    if pgrep -f "run_sync_daemon" > /dev/null; then
        log "✓ Sync daemon service is running"
    else
        log "⚠ WARNING: Sync daemon service may not be running"
    fi

    # 10. (Optional) Reload nginx if used locally
    # log "Reloading nginx..."
    # sudo nginx -s reload

    log "=== V2 deployment completed successfully ==="
}

rollback() {
    log "=== Starting V2 rollback ==="

    source "$VENV_DIR/bin/activate"

    # 1. Restore database from latest backup
    LATEST_BACKUP=$(ls -1t "$BACKUP_DIR"/*.sqlite3 2>/dev/null | head -n 1)
    if [ -z "$LATEST_BACKUP" ]; then
        log "ERROR: No database backup found for rollback."
        exit 1
    fi
    log "Restoring V2 database from backup: $LATEST_BACKUP"
    cp "$LATEST_BACKUP" "$DB_PATH"

    # 2. Checkout previous commit
    if [ ! -f "$COMMIT_FILE" ]; then
        log "ERROR: No previous commit hash found for rollback."
        exit 1
    fi
    PREV_COMMIT=$(cat "$COMMIT_FILE")
    log "Checking out previous commit: $PREV_COMMIT"
    git checkout "$PREV_COMMIT"

    # 3. Install dependencies
    log "Installing Python dependencies..."
    pip install -r requirements.txt

    # 4. Run migrations
    log "Running Django migrations..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py migrate --noinput

    # 5. Collect static files
    log "Collecting static files..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py collectstatic --noinput

    # 6. Stop old Gunicorn process and clean up socket
    log "Stopping old Gunicorn V2..."
    stop_gunicorn
    sleep 2
    cleanup_gunicorn_socket

    log "Restarting V2 Gunicorn server..."
    gunicorn coreproject.wsgi:application \
        --workers 3 \
        --bind unix:"$GUNICORN_SOCK" \
        --timeout 300 \
        --daemon \
        --pid "$GUNICORN_PID"

    sleep 2
    if [ ! -S "$GUNICORN_SOCK" ]; then
        log "ERROR: Gunicorn socket $GUNICORN_SOCK was not created after rollback!"
        exit 1
    fi

    log "=== V2 rollback completed successfully ==="
}

local_dev() {
    log "=== Starting V2 local development services ==="
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings

    stop_gunicorn
    pkill -f "run_sync_daemon.*v2" || true
    pkill -f "process_llm_jobs.*v2" || true

    python3 manage.py runserver 0.0.0.0:8001
}

if [ "$1" == "deploy" ]; then
    deploy
elif [ "$1" == "rollback" ]; then
    rollback
elif [ "$1" == "local" ]; then
    local_dev
else
    echo "Usage: $0 {deploy|rollback|local}"
    echo "  deploy   - Deploy V2 to production"
    echo "  rollback - Rollback V2 to previous version"
    echo "  local    - Run V2 in local development mode"
    exit 1
fi
