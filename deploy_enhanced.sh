#!/bin/bash

# Enhanced Deployment script for Django eval project V2 with LLM Job Auto Processor
# Usage:
#   ./deploy_enhanced.sh deploy    # Deploy latest version with auto processor
#   ./deploy_enhanced.sh rollback  # Rollback to previous version
#   ./deploy_enhanced.sh local     # Run local dev server with auto processor

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
AUTO_PROCESSOR_PID="$PROJECT_DIR/auto_processor_v2.pid"

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

stop_auto_processor() {
    if [ -f "$AUTO_PROCESSOR_PID" ]; then
        log "Stopping Auto Job Processor via PID file..."
        kill "$(cat $AUTO_PROCESSOR_PID)" || true
        rm -f "$AUTO_PROCESSOR_PID"
    else
        log "Stopping Auto Job Processor via pkill fallback..."
        pkill -f "auto_job_processor" || true
    fi
}

backup_critical_data() {
    log "Creating comprehensive backup of critical data..."
    
    # Create timestamped backup directory
    BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    CURRENT_BACKUP_DIR="$BACKUP_DIR/backup_$BACKUP_TIMESTAMP"
    mkdir -p "$CURRENT_BACKUP_DIR"
    
    # Backup entire database
    if [ -f "$DB_PATH" ]; then
        cp "$DB_PATH" "$CURRENT_BACKUP_DIR/db_v2_full_backup.sqlite3"
        log "✓ Full database backed up"
    fi
    
    # Export critical data as JSON fixtures
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    # Backup users and groups
    python3 manage.py dumpdata auth.User auth.Group --indent 2 > "$CURRENT_BACKUP_DIR/users_and_groups.json" || log "⚠ Could not backup users and groups"
    
    # Backup LLM models and jobs
    python3 manage.py dumpdata eval.LLMModel eval.LLMJob --indent 2 > "$CURRENT_BACKUP_DIR/llm_data.json" || log "⚠ Could not backup LLM data"
    
    # Backup projects and tasks
    python3 manage.py dumpdata eval.Project eval.TrainerTask --indent 2 > "$CURRENT_BACKUP_DIR/projects_and_tasks.json" || log "⚠ Could not backup projects and tasks"
    
    # Backup system messages and preferences
    python3 manage.py dumpdata eval.SystemMessage eval.UserPreference --indent 2 > "$CURRENT_BACKUP_DIR/system_config.json" || log "⚠ Could not backup system config"
    
    log "✓ Critical data backed up to $CURRENT_BACKUP_DIR"
    echo "$CURRENT_BACKUP_DIR" > "$BACKUP_DIR/latest_backup_path.txt"
}

restore_critical_data() {
    log "Restoring critical data from backup..."

    # Check if DB already has data (e.g., any users)
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    USER_COUNT=$(python3 manage.py dbshell <<EOF
SELECT COUNT(*) FROM auth_user;
EOF
    2>/dev/null | grep -E '^[0-9]+$' | head -n 1)

    if [ -n "$USER_COUNT" ] && [ "$USER_COUNT" -gt 0 ]; then
        log "Database already contains data (auth_user count: $USER_COUNT), skipping data restore."
        return
    fi

    if [ ! -f "$BACKUP_DIR/latest_backup_path.txt" ]; then
        log "⚠ No backup path found, skipping data restore"
        return
    fi

    RESTORE_DIR=$(cat "$BACKUP_DIR/latest_backup_path.txt")
    if [ ! -d "$RESTORE_DIR" ]; then
        log "⚠ Backup directory $RESTORE_DIR not found, skipping data restore"
        return
    fi

    # Restore users and groups first (most critical)
    if [ -f "$RESTORE_DIR/users_and_groups.json" ]; then
        python3 manage.py loaddata "$RESTORE_DIR/users_and_groups.json" || log "⚠ Could not restore users and groups"
        log "✓ Users and groups restored"
    fi

    # Restore system configuration
    if [ -f "$RESTORE_DIR/system_config.json" ]; then
        python3 manage.py loaddata "$RESTORE_DIR/system_config.json" || log "⚠ Could not restore system config"
        log "✓ System configuration restored"
    fi

    # Restore LLM data
    if [ -f "$RESTORE_DIR/llm_data.json" ]; then
        python3 manage.py loaddata "$RESTORE_DIR/llm_data.json" || log "⚠ Could not restore LLM data"
        log "✓ LLM data restored"
    fi

    # Restore projects and tasks
    if [ -f "$RESTORE_DIR/projects_and_tasks.json" ]; then
        python3 manage.py loaddata "$RESTORE_DIR/projects_and_tasks.json" || log "⚠ Could not restore projects and tasks"
        log "✓ Projects and tasks restored"
    fi
}

safe_migrate() {
    log "Running safe Django migrations..."
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    # Check for migration conflicts first
    log "Checking for migration conflicts..."
    python3 manage.py showmigrations --plan > /tmp/migration_plan.txt
    
    # Run migrations with extra safety
    python3 manage.py migrate --noinput --verbosity=2
    
    log "✓ Migrations completed safely"
}

setup_auto_processor_service() {
    log "Setting up LLM Job Auto Processor service..."
    
    # Check if we're running as root or with sudo
    if [ "$EUID" -eq 0 ] || [ -n "$SUDO_USER" ]; then
        log "Setting up systemd service for auto processor..."
        
        # Get the actual user (not root when using sudo)
        ACTUAL_USER=${SUDO_USER:-$USER}
        ACTUAL_GROUP=$(id -gn $ACTUAL_USER)
        
        # Find Python executable
        PYTHON_PATH="$VENV_DIR/bin/python"
        if [ ! -f "$PYTHON_PATH" ]; then
            PYTHON_PATH=$(which python3)
        fi
        
        # Find service account file
        SERVICE_ACCOUNT_FILE="$PROJECT_DIR/service_account.json"
        
        # Create systemd service file
        SERVICE_FILE="/etc/systemd/system/llm-job-processor.service"
        
        log "Creating systemd service file: $SERVICE_FILE"
        
        cat > $SERVICE_FILE << EOF
[Unit]
Description=LLM Job Auto Processor
After=network.target postgresql.service mysql.service
Wants=network.target

[Service]
Type=simple
User=$ACTUAL_USER
Group=$ACTUAL_GROUP
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$PYTHON_PATH manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed --interval=30
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=llm-job-processor

# Environment variables
Environment=DJANGO_SETTINGS_MODULE=coreproject.settings
Environment=GOOGLE_APPLICATION_CREDENTIALS=$SERVICE_ACCOUNT_FILE

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF
        
        # Set proper permissions
        chmod 644 $SERVICE_FILE
        
        # Reload systemd
        systemctl daemon-reload
        
        # Enable and start the service
        systemctl enable llm-job-processor.service
        systemctl restart llm-job-processor.service
        
        log "✓ Auto processor systemd service configured and started"
        
        # Check service status
        if systemctl is-active --quiet llm-job-processor.service; then
            log "✓ Auto processor service is running"
        else
            log "⚠ Auto processor service may not be running properly"
            systemctl status llm-job-processor.service --no-pager -l || true
        fi
        
    else
        log "Setting up auto processor as background process..."
        
        # Stop any existing auto processor
        stop_auto_processor
        
        # Start auto processor in background
        source "$VENV_DIR/bin/activate"
        export DJANGO_SETTINGS_MODULE=coreproject.settings
        
        nohup python3 manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed > logs/auto_processor_v2.log 2>&1 &
        echo $! > "$AUTO_PROCESSOR_PID"
        
        log "✓ Auto processor started as background process (PID: $(cat $AUTO_PROCESSOR_PID))"
    fi
}

deploy() {
    log "=== Starting Enhanced V2 deployment with Auto Processor ==="

    source "$VENV_DIR/bin/activate"

    # 1. Comprehensive backup of critical data
    backup_critical_data

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

    # 4b. Restore latest DB backup before migrations
    LATEST_BACKUP_DIR=$(ls -td "$BACKUP_DIR"/backup_* 2>/dev/null | head -n 1)
    if [ -d "$LATEST_BACKUP_DIR" ] && [ -f "$LATEST_BACKUP_DIR/db_v2_full_backup.sqlite3" ]; then
        log "Restoring latest DB backup from $LATEST_BACKUP_DIR"
        cp "$LATEST_BACKUP_DIR/db_v2_full_backup.sqlite3" "$DB_PATH"
    else
        log "No valid DB backup found to restore before migrations."
    fi

    # 5. Run safe migrations
    # safe_migrate   # [REMOVED: DB migration step as per new deployment policy]

    # 6. Setup Pub/Sub topics and subscriptions
    log "Setting up Pub/Sub topics and subscriptions..."
    python3 manage.py setup_pubsub

    # 7. Restore critical data if needed
    restore_critical_data

    # 7. Collect static files
    log "Collecting static files..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py collectstatic --noinput

    # 8. Stop old V2 services
    log "Stopping old V2 services..."
    stop_gunicorn
    stop_auto_processor
    pkill -f "process_llm_jobs.*v2" || true
    pkill -f "run_sync_daemon.*v2" || true

    cleanup_gunicorn_socket

    # 9. Start Gunicorn V2
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

    # 10. Setup and start Auto Job Processor
    setup_auto_processor_service

    # 10b. Start LLM Job Pub/Sub Worker
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs)..."
    nohup python3 manage.py process_llm_jobs > logs/process_llm_jobs_v2.log 2>&1 &
    log "✓ process_llm_jobs worker started in background"

    # 11. Start other background services for V2
    log "Starting other background services for V2..."
    nohup python3 run_sync_daemon.py > logs/sync_daemon_v2.log 2>&1 &
    
    # Verify services are running
    sleep 3
    if pgrep -f "run_sync_daemon" > /dev/null; then
        log "✓ Sync daemon service is running"
    else
        log "⚠ WARNING: Sync daemon service may not be running"
    fi

    # 12. Validate all services started correctly
    log "Validating service startup..."
    if validate_services; then
        log "✓ All services validated successfully"
    else
        log "❌ Service validation failed - check logs for details"
        exit 1
    fi

    # 13. Run comprehensive system health check
    log "Running comprehensive system health check..."
    health_check

    log "=== Enhanced V2 deployment completed successfully ==="
    log "🤖 Auto Job Processor is now running and will:"
    log "   ✓ Process pending jobs every 30 seconds"
    log "   ✓ Fix stuck jobs automatically"
    log "   ✓ Retry failed jobs (up to 3 attempts)"
    log "   ✓ Start automatically on system boot"
    log ""
    log "🔍 To monitor the system:"
    log "   ./deploy_enhanced.sh health    # Run health check"
    log "   tail -f logs/auto_processor_v2.log    # Monitor auto processor"
    log "   tail -f logs/process_llm_jobs_v2.log  # Monitor job processor"
}

rollback() {
    log "=== Starting Enhanced V2 rollback ==="

    source "$VENV_DIR/bin/activate"

    # 1. Stop all services first
    log "Stopping all V2 services..."
    stop_gunicorn
    stop_auto_processor
    pkill -f "run_sync_daemon.*v2" || true

    # 2. Restore database from latest backup
    if [ -f "$BACKUP_DIR/latest_backup_path.txt" ]; then
        RESTORE_DIR=$(cat "$BACKUP_DIR/latest_backup_path.txt")
        LATEST_BACKUP="$RESTORE_DIR/db_v2_full_backup.sqlite3"
    else
        LATEST_BACKUP=$(ls -1t "$BACKUP_DIR"/*.sqlite3 2>/dev/null | head -n 1)
    fi
    
    if [ -z "$LATEST_BACKUP" ] || [ ! -f "$LATEST_BACKUP" ]; then
        log "ERROR: No database backup found for rollback."
        exit 1
    fi
    log "Restoring V2 database from backup: $LATEST_BACKUP"
    cp "$LATEST_BACKUP" "$DB_PATH"

    # 3. Checkout previous commit
    if [ ! -f "$COMMIT_FILE" ]; then
        log "ERROR: No previous commit hash found for rollback."
        exit 1
    fi
    PREV_COMMIT=$(cat "$COMMIT_FILE")
    log "Checking out previous commit: $PREV_COMMIT"
    git checkout "$PREV_COMMIT"

    # 4. Install dependencies
    log "Installing Python dependencies..."
    pip install -r requirements.txt

    # 4b. Restore latest DB backup before migrations
    LATEST_BACKUP_DIR=$(ls -td "$BACKUP_DIR"/backup_* 2>/dev/null | head -n 1)
    if [ -d "$LATEST_BACKUP_DIR" ] && [ -f "$LATEST_BACKUP_DIR/db_v2_full_backup.sqlite3" ]; then
        log "Restoring latest DB backup from $LATEST_BACKUP_DIR"
        cp "$LATEST_BACKUP_DIR/db_v2_full_backup.sqlite3" "$DB_PATH"
    else
        log "No valid DB backup found to restore before migrations."
    fi

    # 5. Run migrations
    # safe_migrate   # [REMOVED: DB migration step as per new deployment policy]

    # 6. Collect static files
    log "Collecting static files..."
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    python3 manage.py collectstatic --noinput

    # 7. Restart services
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

    # 8. Restart auto processor
    setup_auto_processor_service

    # 8b. Start LLM Job Pub/Sub Worker
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs)..."
    nohup python3 manage.py process_llm_jobs > logs/process_llm_jobs_v2.log 2>&1 &
    log "✓ process_llm_jobs worker started in background"

    log "=== Enhanced V2 rollback completed successfully ==="
}

local_dev() {
    log "=== Starting Enhanced V2 local development services ==="
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings

    stop_gunicorn
    stop_auto_processor
    pkill -f "run_sync_daemon.*v2" || true

    # Start auto processor in background for local development
    log "Starting auto processor for local development..."
    nohup python3 manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed > logs/auto_processor_local.log 2>&1 &
    echo $! > "$AUTO_PROCESSOR_PID"
    log "✓ Auto processor started (PID: $(cat $AUTO_PROCESSOR_PID))"

    # Start LLM Job Pub/Sub Worker for local development
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs) for local development..."
    nohup python3 manage.py process_llm_jobs > logs/process_llm_jobs_local.log 2>&1 &
    log "✓ process_llm_jobs worker started in background"

    log "Starting Django development server with auto processor running..."
    python3 manage.py runserver 0.0.0.0:8001
}

# Enhanced health check function
health_check() {
    log "=== Running comprehensive system health check ==="
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    # 1. Run LLM job diagnostics
    log "Running LLM job diagnostics..."
    python3 manage.py llm_job_diagnostics
    
    # 2. Check auto processor status
    log "Checking Auto Job Processor status..."
    if systemctl is-active --quiet llm-job-processor.service 2>/dev/null; then
        log "✓ Auto processor systemd service is running"
        systemctl status llm-job-processor.service --no-pager -l | head -10
    elif [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
        log "✓ Auto processor background process is running (PID: $(cat $AUTO_PROCESSOR_PID))"
    else
        log "❌ Auto processor is not running"
    fi
    
    # 3. Check process_llm_jobs worker status
    log "Checking LLM Job Pub/Sub Worker status..."
    if pgrep -f "process_llm_jobs" > /dev/null; then
        WORKER_PID=$(pgrep -f "process_llm_jobs")
        log "✓ process_llm_jobs worker is running (PID: $WORKER_PID)"
    else
        log "❌ process_llm_jobs worker is not running"
    fi
    
    # 4. Check Gunicorn status
    log "Checking Gunicorn status..."
    if [ -f "$GUNICORN_PID" ] && kill -0 "$(cat $GUNICORN_PID)" 2>/dev/null; then
        log "✓ Gunicorn is running (PID: $(cat $GUNICORN_PID))"
    else
        log "❌ Gunicorn is not running"
    fi
    
    # 5. Check socket file
    if [ -S "$GUNICORN_SOCK" ]; then
        log "✓ Gunicorn socket exists: $GUNICORN_SOCK"
    else
        log "❌ Gunicorn socket missing: $GUNICORN_SOCK"
    fi
    
    # 6. Validate Pub/Sub configuration
    log "Validating Pub/Sub configuration..."
    python3 -c "
from django.conf import settings
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coreproject.settings')
import django
django.setup()

print(f'✓ Project ID: {settings.GOOGLE_CLOUD_PROJECT_ID}')
print(f'✓ LLM Requests Topic: {settings.PUBSUB_TOPIC_LLM_REQUESTS}')
print(f'✓ LLM Requests Subscription: {settings.PUBSUB_SUB_LLM_REQUESTS}')
print(f'✓ Service Account File: {settings.SERVICE_ACCOUNT_FILE}')

# Check if service account file exists
if os.path.exists(settings.SERVICE_ACCOUNT_FILE):
    print(f'✓ Service account file exists')
else:
    print(f'❌ Service account file missing: {settings.SERVICE_ACCOUNT_FILE}')
"
    
    # 7. Check recent logs for errors
    log "Checking recent logs for errors..."
    if [ -f "logs/auto_processor_v2.log" ]; then
        ERROR_COUNT=$(tail -50 logs/auto_processor_v2.log | grep -i error | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            log "⚠ Found $ERROR_COUNT recent errors in auto processor log"
            tail -10 logs/auto_processor_v2.log | grep -i error || true
        else
            log "✓ No recent errors in auto processor log"
        fi
    fi
    
    if [ -f "logs/process_llm_jobs_v2.log" ]; then
        ERROR_COUNT=$(tail -50 logs/process_llm_jobs_v2.log | grep -i error | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            log "⚠ Found $ERROR_COUNT recent errors in process_llm_jobs log"
            tail -10 logs/process_llm_jobs_v2.log | grep -i error || true
        else
            log "✓ No recent errors in process_llm_jobs log"
        fi
    fi
    
    log "=== Health check completed ==="
}

# Function to validate service startup
validate_services() {
    log "=== Validating service startup ==="
    
    # Wait a moment for services to initialize
    sleep 5
    
    # Check Gunicorn
    if [ ! -S "$GUNICORN_SOCK" ]; then
        log "❌ ERROR: Gunicorn socket not created after startup"
        return 1
    fi
    
    # Check auto processor
    AUTO_PROCESSOR_RUNNING=false
    if systemctl is-active --quiet llm-job-processor.service 2>/dev/null; then
        AUTO_PROCESSOR_RUNNING=true
    elif [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
        AUTO_PROCESSOR_RUNNING=true
    fi
    
    if [ "$AUTO_PROCESSOR_RUNNING" = false ]; then
        log "❌ ERROR: Auto processor not running after startup"
        return 1
    fi
    
    # Check process_llm_jobs worker
    if ! pgrep -f "process_llm_jobs" > /dev/null; then
        log "❌ ERROR: process_llm_jobs worker not running after startup"
        return 1
    fi
    
    log "✓ All critical services validated successfully"
    return 0
}

# =============================================================================
# MODULAR SERVICE MANAGEMENT FUNCTIONS
# =============================================================================

start_app_server() {
    log "Starting Gunicorn V2 app server..."
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    cleanup_gunicorn_socket
    
    gunicorn coreproject.wsgi:application \
        --workers 3 \
        --bind unix:"$GUNICORN_SOCK" \
        --timeout 300 \
        --daemon \
        --pid "$GUNICORN_PID" \
        --access-logfile "$PROJECT_DIR/logs/v2_access.log" \
        --error-logfile "$PROJECT_DIR/logs/v2_error.log"

    sleep 2
    if [ -S "$GUNICORN_SOCK" ]; then
        log "✓ Gunicorn app server started successfully"
        return 0
    else
        log "❌ ERROR: Gunicorn socket $GUNICORN_SOCK was not created!"
        return 1
    fi
}

start_auto_processor_service() {
    log "Starting LLM Job Auto Processor..."
    
    # Check if we're running as root or with sudo
    if [ "$EUID" -eq 0 ] || [ -n "$SUDO_USER" ]; then
        log "Starting systemd service for auto processor..."
        systemctl restart llm-job-processor.service
        
        sleep 2
        if systemctl is-active --quiet llm-job-processor.service; then
            log "✓ Auto processor systemd service started successfully"
            return 0
        else
            log "❌ Auto processor systemd service failed to start"
            systemctl status llm-job-processor.service --no-pager -l || true
            return 1
        fi
    else
        log "Starting auto processor as background process..."
        source "$VENV_DIR/bin/activate"
        export DJANGO_SETTINGS_MODULE=coreproject.settings
        
        nohup python3 manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed > logs/auto_processor_v2.log 2>&1 &
        echo $! > "$AUTO_PROCESSOR_PID"
        
        sleep 2
        if [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
            log "✓ Auto processor started successfully (PID: $(cat $AUTO_PROCESSOR_PID))"
            return 0
        else
            log "❌ Auto processor failed to start"
            return 1
        fi
    fi
}

start_pubsub_worker() {
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs)..."
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    nohup python3 manage.py process_llm_jobs > logs/process_llm_jobs_v2.log 2>&1 &
    
    sleep 2
    if pgrep -f "process_llm_jobs" > /dev/null; then
        WORKER_PID=$(pgrep -f "process_llm_jobs")
        log "✓ Pub/Sub worker started successfully (PID: $WORKER_PID)"
        return 0
    else
        log "❌ Pub/Sub worker failed to start"
        return 1
    fi
}

start_sync_daemon() {
    log "Starting sync daemon service..."
    source "$VENV_DIR/bin/activate"
    
    nohup python3 run_sync_daemon.py > logs/sync_daemon_v2.log 2>&1 &
    
    sleep 2
    if pgrep -f "run_sync_daemon" > /dev/null; then
        DAEMON_PID=$(pgrep -f "run_sync_daemon")
        log "✓ Sync daemon started successfully (PID: $DAEMON_PID)"
        return 0
    else
        log "❌ Sync daemon failed to start"
        return 1
    fi
}

stop_pubsub_worker() {
    log "Stopping LLM Job Pub/Sub Worker..."
    pkill -f "process_llm_jobs" || true
    sleep 1
    if ! pgrep -f "process_llm_jobs" > /dev/null; then
        log "✓ Pub/Sub worker stopped successfully"
    else
        log "⚠ Pub/Sub worker may still be running"
    fi
}

stop_sync_daemon() {
    log "Stopping sync daemon..."
    pkill -f "run_sync_daemon" || true
    sleep 1
    if ! pgrep -f "run_sync_daemon" > /dev/null; then
        log "✓ Sync daemon stopped successfully"
    else
        log "⚠ Sync daemon may still be running"
    fi
}

# =============================================================================
# MODULAR SERVICE COMMANDS
# =============================================================================

restart_app_server() {
    log "=== Restarting App Server (Gunicorn) ==="
    stop_gunicorn
    if start_app_server; then
        log "✓ App server restarted successfully"
    else
        log "❌ App server restart failed"
        exit 1
    fi
}

restart_auto_processor() {
    log "=== Restarting Auto Processor ==="
    stop_auto_processor
    if start_auto_processor_service; then
        log "✓ Auto processor restarted successfully"
    else
        log "❌ Auto processor restart failed"
        exit 1
    fi
}

restart_pubsub_worker() {
    log "=== Restarting Pub/Sub Worker ==="
    stop_pubsub_worker
    if start_pubsub_worker; then
        log "✓ Pub/Sub worker restarted successfully"
    else
        log "❌ Pub/Sub worker restart failed"
        exit 1
    fi
}

restart_sync_daemon() {
    log "=== Restarting Sync Daemon ==="
    stop_sync_daemon
    if start_sync_daemon; then
        log "✓ Sync daemon restarted successfully"
    else
        log "❌ Sync daemon restart failed"
        exit 1
    fi
}

stop_all_services() {
    log "=== Stopping All Services ==="
    stop_gunicorn
    stop_auto_processor
    stop_pubsub_worker
    stop_sync_daemon
    log "✓ All services stopped"
}

start_all_services() {
    log "=== Starting All Services ==="
    
    # Start services in order
    if ! start_app_server; then
        log "❌ Failed to start app server"
        exit 1
    fi
    
    if ! start_auto_processor_service; then
        log "❌ Failed to start auto processor"
        exit 1
    fi
    
    if ! start_pubsub_worker; then
        log "❌ Failed to start Pub/Sub worker"
        exit 1
    fi
    
    if ! start_sync_daemon; then
        log "❌ Failed to start sync daemon"
        exit 1
    fi
    
    log "✓ All services started successfully"
}

status_services() {
    log "=== Service Status Check ==="
    
    # Check Gunicorn
    if [ -f "$GUNICORN_PID" ] && kill -0 "$(cat $GUNICORN_PID)" 2>/dev/null; then
        log "✓ Gunicorn: RUNNING (PID: $(cat $GUNICORN_PID))"
    else
        log "❌ Gunicorn: NOT RUNNING"
    fi
    
    # Check socket
    if [ -S "$GUNICORN_SOCK" ]; then
        log "✓ Gunicorn Socket: EXISTS"
    else
        log "❌ Gunicorn Socket: MISSING"
    fi
    
    # Check auto processor
    if systemctl is-active --quiet llm-job-processor.service 2>/dev/null; then
        log "✓ Auto Processor: RUNNING (systemd service)"
    elif [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
        log "✓ Auto Processor: RUNNING (PID: $(cat $AUTO_PROCESSOR_PID))"
    else
        log "❌ Auto Processor: NOT RUNNING"
    fi
    
    # Check Pub/Sub worker
    if pgrep -f "process_llm_jobs" > /dev/null; then
        WORKER_PID=$(pgrep -f "process_llm_jobs")
        log "✓ Pub/Sub Worker: RUNNING (PID: $WORKER_PID)"
    else
        log "❌ Pub/Sub Worker: NOT RUNNING"
    fi
    
    # Check sync daemon
    if pgrep -f "run_sync_daemon" > /dev/null; then
        DAEMON_PID=$(pgrep -f "run_sync_daemon")
        log "✓ Sync Daemon: RUNNING (PID: $DAEMON_PID)"
    else
        log "❌ Sync Daemon: NOT RUNNING"
    fi
    
    log "=== Status check completed ==="
}

if [ "$1" == "deploy" ]; then
    deploy
elif [ "$1" == "rollback" ]; then
    rollback
elif [ "$1" == "local" ]; then
    local_dev
elif [ "$1" == "health" ]; then
    health_check
elif [ "$1" == "restart_app_server" ]; then
    restart_app_server
elif [ "$1" == "restart_auto_processor" ]; then
    restart_auto_processor
elif [ "$1" == "restart_pubsub_worker" ]; then
    restart_pubsub_worker
elif [ "$1" == "restart_sync_daemon" ]; then
    restart_sync_daemon
elif [ "$1" == "stop_all_services" ]; then
    stop_all_services
elif [ "$1" == "start_all_services" ]; then
    start_all_services
elif [ "$1" == "status_services" ] || [ "$1" == "status" ]; then
    status_services
else
    echo "Usage: $0 {deploy|rollback|local|health|restart_app_server|restart_auto_processor|restart_pubsub_worker|restart_sync_daemon|stop_all_services|start_all_services|status}"
    echo ""
    echo "DEPLOYMENT COMMANDS:"
    echo "  deploy                - Deploy V2 to production with auto processor"
    echo "  rollback              - Rollback V2 to previous version"
    echo "  local                 - Run V2 in local development mode with auto processor"
    echo "  health                - Run comprehensive system health check"
    echo ""
    echo "SERVICE MANAGEMENT COMMANDS:"
    echo "  restart_app_server    - Restart only Gunicorn app server"
    echo "  restart_auto_processor - Restart only LLM job auto processor"
    echo "  restart_pubsub_worker - Restart only Pub/Sub worker (process_llm_jobs)"
    echo "  restart_sync_daemon   - Restart only sync daemon"
    echo "  stop_all_services     - Stop all services without redeployment"
    echo "  start_all_services    - Start all services without redeployment"
    echo "  status                - Show status of all services"
    echo ""
    echo "EXAMPLES:"
    echo "  ./deploy_enhanced.sh restart_app_server    # Quick Gunicorn restart"
    echo "  ./deploy_enhanced.sh status                # Check service status"
    echo "  ./deploy_enhanced.sh stop_all_services     # Stop everything"
    exit 1
fi
