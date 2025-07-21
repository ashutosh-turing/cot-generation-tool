#!/bin/bash

# Database backup script for eval project
# Creates daily backups of the SQLite database with rotation

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/db_backups"
DB_PATH="$SCRIPT_DIR/db.sqlite3"
MAX_BACKUPS=14  # Keep two weeks of daily backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="db_backup_${TIMESTAMP}.sqlite3"
LOG_FILE="$SCRIPT_DIR/logs/db_backup.log"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"
mkdir -p "$SCRIPT_DIR/logs"

# Log function
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    echo "$1"
}

# Check if database file exists
if [ ! -f "$DB_PATH" ]; then
    log_message "ERROR: Database file not found at $DB_PATH"
    exit 1
fi

# Create backup
log_message "Creating backup: $BACKUP_NAME"

# Use sqlite3 to create a proper backup (this ensures database integrity)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/$BACKUP_NAME'" 2>> "$LOG_FILE"

if [ $? -eq 0 ]; then
    log_message "Backup created successfully at $BACKUP_DIR/$BACKUP_NAME"
    
    # Create a symlink to the latest backup for easy access
    rm -f "$BACKUP_DIR/latest.sqlite3" 2>/dev/null
    ln -s "$BACKUP_DIR/$BACKUP_NAME" "$BACKUP_DIR/latest.sqlite3"
    log_message "Updated latest.sqlite3 symlink"
    
    # Rotate old backups (keep only MAX_BACKUPS most recent)
    backup_count=$(ls -1 "$BACKUP_DIR"/*.sqlite3 2>/dev/null | grep -v "latest.sqlite3" | wc -l)
    
    if [ "$backup_count" -gt "$MAX_BACKUPS" ]; then
        files_to_delete=$((backup_count - MAX_BACKUPS))
        log_message "Rotating backups: removing $files_to_delete old backup(s)"
        
        ls -1t "$BACKUP_DIR"/*.sqlite3 | grep -v "latest.sqlite3" | tail -n "$files_to_delete" | xargs rm -f
    fi
else
    log_message "ERROR: Backup failed"
    exit 1
fi

log_message "Backup process completed"

# Create a simple backup report
echo "=== Database Backup Report ===" > "$BACKUP_DIR/backup_report.txt"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')" >> "$BACKUP_DIR/backup_report.txt"
echo "Latest backup: $BACKUP_NAME" >> "$BACKUP_DIR/backup_report.txt"
echo "Total backups: $(ls -1 "$BACKUP_DIR"/*.sqlite3 2>/dev/null | grep -v "latest.sqlite3" | wc -l)" >> "$BACKUP_DIR/backup_report.txt"
echo "Backup location: $BACKUP_DIR" >> "$BACKUP_DIR/backup_report.txt"

log_message "Backup report generated at $BACKUP_DIR/backup_report.txt"

exit 0
