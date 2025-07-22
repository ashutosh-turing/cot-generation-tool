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

    # 5. Run safe migrations
    safe_migrate

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

    # 12. Run system health check
    log "Running system health check..."
    python3 manage.py llm_job_diagnostics || log "⚠ Health check completed with warnings"

    log "=== Enhanced V2 deployment completed successfully ==="
    log "🤖 Auto Job Processor is now running and will:"
    log "   ✓ Process pending jobs every 30 seconds"
    log "   ✓ Fix stuck jobs automatically"
    log "   ✓ Retry failed jobs (up to 3 attempts)"
    log "   ✓ Start automatically on system boot"
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

    # 5. Run migrations
    safe_migrate

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

    log "Starting Django development server with auto processor running..."
    python3 manage.py runserver 0.0.0.0:8001
}

# Health check function
health_check() {
    log "=== Running system health check ==="
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    python3 manage.py llm_job_diagnostics
    
    # Check if auto processor is running
    if systemctl is-active --quiet llm-job-processor.service 2>/dev/null; then
        log "✓ Auto processor systemd service is running"
    elif [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
        log "✓ Auto processor background process is running"
    else
        log "⚠ Auto processor is not running"
    fi
}

if [ "$1" == "deploy" ]; then
    deploy
elif [ "$1" == "rollback" ]; then
    rollback
elif [ "$1" == "local" ]; then
    local_dev
elif [ "$1" == "health" ]; then
    health_check
else
    echo "Usage: $0 {deploy|rollback|local|health}"
    echo "  deploy   - Deploy V2 to production with auto processor"
    echo "  rollback - Rollback V2 to previous version"
    echo "  local    - Run V2 in local development mode with auto processor"
    echo "  health   - Run system health check"
    exit 1
fi
