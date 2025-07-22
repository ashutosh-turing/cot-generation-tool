#!/bin/bash

# Local Development Deployment script for Django eval project V2 with LLM Job Auto Processor
# Usage:
#   ./deploy_local.sh deploy    # Deploy locally with auto processor
#   ./deploy_local.sh health    # Run health check
#   ./deploy_local.sh local     # Run local dev server with auto processor

set -e

# Local Configuration (adapted for current directory)
PROJECT_DIR="$(pwd)"
DB_PATH="$PROJECT_DIR/db.sqlite3"
BACKUP_DIR="$PROJECT_DIR/db_backups"
COMMIT_FILE="$PROJECT_DIR/last_deploy_commit.txt"
LOG_FILE="$PROJECT_DIR/logs/deploy.log"
VENV_DIR="$PROJECT_DIR"  # We're already in the virtual environment
GUNICORN_SOCK="$PROJECT_DIR/gunicorn.sock"
GUNICORN_PID="$PROJECT_DIR/gunicorn.pid"
AUTO_PROCESSOR_PID="$PROJECT_DIR/auto_processor.pid"

log() {
    mkdir -p "$PROJECT_DIR/logs"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
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

# Enhanced health check function
health_check() {
    log "=== Running comprehensive system health check ==="
    
    # Activate virtual environment if needed
    if [ -f "bin/activate" ]; then
        source bin/activate
    fi
    
    export DJANGO_SETTINGS_MODULE=coreproject.settings
    
    # 1. Run LLM job diagnostics
    log "Running LLM job diagnostics..."
    python manage.py llm_job_diagnostics || log "⚠ Diagnostics completed with warnings"
    
    # 2. Check auto processor status
    log "Checking Auto Job Processor status..."
    if [ -f "$AUTO_PROCESSOR_PID" ] && kill -0 "$(cat $AUTO_PROCESSOR_PID)" 2>/dev/null; then
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
    
    # 4. Validate Pub/Sub configuration
    log "Validating Pub/Sub configuration..."
    python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coreproject.settings')
import django
django.setup()
from django.conf import settings

try:
    print(f'✓ Project ID: {settings.GOOGLE_CLOUD_PROJECT_ID}')
    print(f'✓ LLM Requests Topic: {settings.PUBSUB_TOPIC_LLM_REQUESTS}')
    print(f'✓ LLM Requests Subscription: {settings.PUBSUB_SUB_LLM_REQUESTS}')
    print(f'✓ Service Account File: {settings.SERVICE_ACCOUNT_FILE}')
    
    # Check if service account file exists
    if os.path.exists(settings.SERVICE_ACCOUNT_FILE):
        print(f'✓ Service account file exists')
    else:
        print(f'❌ Service account file missing: {settings.SERVICE_ACCOUNT_FILE}')
except Exception as e:
    print(f'⚠ Error checking settings: {e}')
" || log "⚠ Could not validate Pub/Sub configuration"
    
    # 5. Check recent logs for errors
    log "Checking recent logs for errors..."
    if [ -f "logs/auto_processor.log" ]; then
        ERROR_COUNT=$(tail -50 logs/auto_processor.log 2>/dev/null | grep -i error | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            log "⚠ Found $ERROR_COUNT recent errors in auto processor log"
            tail -10 logs/auto_processor.log | grep -i error || true
        else
            log "✓ No recent errors in auto processor log"
        fi
    fi
    
    if [ -f "logs/process_llm_jobs.log" ]; then
        ERROR_COUNT=$(tail -50 logs/process_llm_jobs.log 2>/dev/null | grep -i error | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            log "⚠ Found $ERROR_COUNT recent errors in process_llm_jobs log"
            tail -10 logs/process_llm_jobs.log | grep -i error || true
        else
            log "✓ No recent errors in process_llm_jobs log"
        fi
    fi
    
    log "=== Health check completed ==="
}

local_dev() {
    log "=== Starting Local Development Services ==="
    
    # Activate virtual environment if needed
    if [ -f "bin/activate" ]; then
        source bin/activate
    fi
    
    export DJANGO_SETTINGS_MODULE=coreproject.settings

    # Stop any existing processes
    stop_auto_processor
    pkill -f "process_llm_jobs" || true

    # Start auto processor in background for local development
    log "Starting auto processor for local development..."
    nohup python manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed > logs/auto_processor.log 2>&1 &
    echo $! > "$AUTO_PROCESSOR_PID"
    log "✓ Auto processor started (PID: $(cat $AUTO_PROCESSOR_PID))"

    # Start LLM Job Pub/Sub Worker for local development
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs) for local development..."
    nohup python manage.py process_llm_jobs > logs/process_llm_jobs.log 2>&1 &
    log "✓ process_llm_jobs worker started in background"

    log "Starting Django development server with auto processor running..."
    log "🔍 To monitor the system:"
    log "   ./deploy_local.sh health    # Run health check"
    log "   tail -f logs/auto_processor.log    # Monitor auto processor"
    log "   tail -f logs/process_llm_jobs.log  # Monitor job processor"
    log ""
    
    python manage.py runserver 0.0.0.0:8000
}

deploy() {
    log "=== Starting Local Deployment ==="
    
    # Activate virtual environment if needed
    if [ -f "bin/activate" ]; then
        source bin/activate
    fi
    
    export DJANGO_SETTINGS_MODULE=coreproject.settings

    # 1. Setup Pub/Sub topics and subscriptions
    log "Setting up Pub/Sub topics and subscriptions..."
    python manage.py setup_pubsub || log "⚠ Pub/Sub setup completed with warnings"

    # 2. Run migrations
    log "Running Django migrations..."
    python manage.py migrate --noinput || log "⚠ Migrations completed with warnings"

    # 3. Collect static files
    log "Collecting static files..."
    python manage.py collectstatic --noinput || log "⚠ Static files collection completed with warnings"

    # 4. Stop any existing processes
    log "Stopping existing processes..."
    stop_auto_processor
    pkill -f "process_llm_jobs" || true

    # 5. Start auto processor
    log "Starting auto processor..."
    nohup python manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed > logs/auto_processor.log 2>&1 &
    echo $! > "$AUTO_PROCESSOR_PID"
    log "✓ Auto processor started (PID: $(cat $AUTO_PROCESSOR_PID))"

    # 6. Start LLM Job Pub/Sub Worker
    log "Starting LLM Job Pub/Sub Worker (process_llm_jobs)..."
    nohup python manage.py process_llm_jobs > logs/process_llm_jobs.log 2>&1 &
    log "✓ process_llm_jobs worker started in background"

    # 7. Wait a moment and validate services
    sleep 3
    
    # 8. Run health check
    log "Running system health check..."
    health_check

    log "=== Local deployment completed successfully ==="
    log "🤖 Auto Job Processor is now running and will:"
    log "   ✓ Process pending jobs every 30 seconds"
    log "   ✓ Fix stuck jobs automatically"
    log "   ✓ Retry failed jobs (up to 3 attempts)"
    log ""
    log "🔍 To monitor the system:"
    log "   ./deploy_local.sh health    # Run health check"
    log "   tail -f logs/auto_processor.log    # Monitor auto processor"
    log "   tail -f logs/process_llm_jobs.log  # Monitor job processor"
    log ""
    log "To start the development server:"
    log "   ./deploy_local.sh local"
}

if [ "$1" == "deploy" ]; then
    deploy
elif [ "$1" == "local" ]; then
    local_dev
elif [ "$1" == "health" ]; then
    health_check
else
    echo "Usage: $0 {deploy|local|health}"
    echo "  deploy   - Deploy locally with auto processor"
    echo "  local    - Run local development server with auto processor"
    echo "  health   - Run system health check"
    exit 1
fi
