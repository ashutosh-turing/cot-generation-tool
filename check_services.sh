#!/bin/bash

# Service status checker for the evaluation system
# Usage: ./check_services.sh

echo "=== Service Status Check ==="
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo

# Check Gunicorn
echo "🔍 Checking Gunicorn..."
if pgrep -f "gunicorn.*coreproject" > /dev/null; then
    echo "✅ Gunicorn is running"
    echo "   PID(s): $(pgrep -f 'gunicorn.*coreproject' | tr '\n' ' ')"
else
    echo "❌ Gunicorn is NOT running"
fi

# Check Gunicorn socket
GUNICORN_SOCK="/home/cot-generation-tool/gunicorn_v2.sock"
if [ -S "$GUNICORN_SOCK" ]; then
    echo "✅ Gunicorn socket exists: $GUNICORN_SOCK"
else
    echo "❌ Gunicorn socket missing: $GUNICORN_SOCK"
fi

echo

# Check LLM Job Processing Service
echo "🔍 Checking LLM Job Processing Service..."
if pgrep -f "process_llm_jobs" > /dev/null; then
    echo "✅ LLM job processing service is running"
    echo "   PID(s): $(pgrep -f 'process_llm_jobs' | tr '\n' ' ')"
else
    echo "❌ LLM job processing service is NOT running"
fi

echo

# Check Sync Daemon
echo "🔍 Checking Sync Daemon..."
if pgrep -f "run_sync_daemon" > /dev/null; then
    echo "✅ Sync daemon is running"
    echo "   PID(s): $(pgrep -f 'run_sync_daemon' | tr '\n' ' ')"
else
    echo "❌ Sync daemon is NOT running"
fi

echo

# Check log files
echo "🔍 Checking log files..."
LOG_DIR="/home/cot-generation-tool/logs"
if [ -d "$LOG_DIR" ]; then
    echo "📁 Log directory: $LOG_DIR"
    
    # Check recent log entries
    if [ -f "$LOG_DIR/llm_jobs_v2.log" ]; then
        echo "📄 LLM Jobs log (last 3 lines):"
        tail -n 3 "$LOG_DIR/llm_jobs_v2.log" | sed 's/^/   /'
    else
        echo "❌ LLM Jobs log file missing"
    fi
    
    if [ -f "$LOG_DIR/sync_daemon_v2.log" ]; then
        echo "📄 Sync Daemon log (last 3 lines):"
        tail -n 3 "$LOG_DIR/sync_daemon_v2.log" | sed 's/^/   /'
    else
        echo "❌ Sync Daemon log file missing"
    fi
    
    if [ -f "$LOG_DIR/v2_error.log" ]; then
        echo "📄 Gunicorn error log (last 3 lines):"
        tail -n 3 "$LOG_DIR/v2_error.log" | sed 's/^/   /'
    else
        echo "❌ Gunicorn error log file missing"
    fi
else
    echo "❌ Log directory missing: $LOG_DIR"
fi

echo

# Check database
echo "🔍 Checking database..."
DB_PATH="/home/cot-generation-tool/db_v2.sqlite3"
if [ -f "$DB_PATH" ]; then
    echo "✅ Database file exists: $DB_PATH"
    echo "   Size: $(du -h "$DB_PATH" | cut -f1)"
    echo "   Modified: $(stat -c %y "$DB_PATH")"
else
    echo "❌ Database file missing: $DB_PATH"
fi

echo

# Summary
echo "=== Summary ==="
SERVICES_RUNNING=0
TOTAL_SERVICES=3

if pgrep -f "gunicorn.*coreproject" > /dev/null; then
    ((SERVICES_RUNNING++))
fi

if pgrep -f "process_llm_jobs" > /dev/null; then
    ((SERVICES_RUNNING++))
fi

if pgrep -f "run_sync_daemon" > /dev/null; then
    ((SERVICES_RUNNING++))
fi

echo "Services running: $SERVICES_RUNNING/$TOTAL_SERVICES"

if [ $SERVICES_RUNNING -eq $TOTAL_SERVICES ]; then
    echo "🎉 All services are running correctly!"
    exit 0
elif [ $SERVICES_RUNNING -gt 0 ]; then
    echo "⚠️  Some services are not running. Check the details above."
    exit 1
else
    echo "🚨 No services are running! Please run deployment or start services manually."
    exit 2
fi
