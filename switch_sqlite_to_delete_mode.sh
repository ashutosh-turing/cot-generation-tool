#!/bin/bash

# Script to safely switch SQLite DB from WAL mode to DELETE mode
# and remove .wal/.shm files for db_v2.sqlite3

set -e

DB_PATH="/home/cot-generation-tool/db_v2.sqlite3"
GUNICORN_PID="/home/cot-generation-tool/gunicorn_v2.pid"
AUTO_PROCESSOR_PID="/home/cot-generation-tool/auto_processor_v2.pid"

echo "==== Switching SQLite DB to DELETE journal mode and cleaning up WAL/SHM files ===="

# 1. Stop all Django-related services/processes
echo "Stopping Gunicorn and auto processor (if running)..."
if [ -f "$GUNICORN_PID" ]; then
    kill "$(cat $GUNICORN_PID)" || true
    rm -f "$GUNICORN_PID"
fi
if [ -f "$AUTO_PROCESSOR_PID" ]; then
    kill "$(cat $AUTO_PROCESSOR_PID)" || true
    rm -f "$AUTO_PROCESSOR_PID"
fi
pkill -f "process_llm_jobs" || true
pkill -f "run_sync_daemon" || true

sleep 2

# 2. Switch journal mode to DELETE and checkpoint WAL
echo "Switching journal mode to DELETE and checkpointing WAL..."
sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(FULL);"
sqlite3 "$DB_PATH" "PRAGMA journal_mode=DELETE;"

# 3. Remove .wal and .shm files if they exist
WAL_FILE="${DB_PATH}-wal"
SHM_FILE="${DB_PATH}-shm"
if [ -f "$WAL_FILE" ]; then
    echo "Removing $WAL_FILE"
    rm -f "$WAL_FILE"
fi
if [ -f "$SHM_FILE" ]; then
    echo "Removing $SHM_FILE"
    rm -f "$SHM_FILE"
fi

echo "==== SQLite DB is now in DELETE mode. WAL/SHM files cleaned up. ===="

echo "You may now restart your Django services as needed."
