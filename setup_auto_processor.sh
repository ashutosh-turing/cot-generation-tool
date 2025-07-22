#!/bin/bash

# Setup script for LLM Job Auto Processor
# This script sets up the auto processor as a systemd service for production

echo "🔧 Setting up LLM Job Auto Processor for Production"
echo "=================================================="

# Get current directory
CURRENT_DIR=$(pwd)
PROJECT_DIR=$(realpath $CURRENT_DIR)

# Check if we're in the right directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: manage.py not found. Please run this script from the Django project root."
    exit 1
fi

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: This script needs to be run with sudo privileges to set up systemd service."
    echo "Usage: sudo ./setup_auto_processor.sh"
    exit 1
fi

# Get the actual user (not root when using sudo)
ACTUAL_USER=${SUDO_USER:-$USER}
ACTUAL_GROUP=$(id -gn $ACTUAL_USER)

echo "📁 Project directory: $PROJECT_DIR"
echo "👤 Running as user: $ACTUAL_USER:$ACTUAL_GROUP"

# Find Python executable
PYTHON_PATH="$PROJECT_DIR/bin/python"
if [ ! -f "$PYTHON_PATH" ]; then
    PYTHON_PATH=$(which python3)
    if [ ! -f "$PYTHON_PATH" ]; then
        PYTHON_PATH=$(which python)
    fi
fi

echo "🐍 Python path: $PYTHON_PATH"

# Find service account file
SERVICE_ACCOUNT_FILE="$PROJECT_DIR/service_account.json"
if [ ! -f "$SERVICE_ACCOUNT_FILE" ]; then
    echo "⚠️  Service account file not found at $SERVICE_ACCOUNT_FILE"
    echo "Please ensure your Google Cloud service account file is available."
fi

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/llm-job-processor.service"

echo "📝 Creating systemd service file: $SERVICE_FILE"

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
Environment=PATH=$PROJECT_DIR/bin:/usr/local/bin:/usr/bin:/bin
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
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

# Enable the service
echo "✅ Enabling LLM Job Auto Processor service..."
systemctl enable llm-job-processor.service

# Start the service
echo "🚀 Starting LLM Job Auto Processor service..."
systemctl start llm-job-processor.service

# Check status
echo ""
echo "📊 Service Status:"
systemctl status llm-job-processor.service --no-pager -l

echo ""
echo "✅ Setup Complete!"
echo ""
echo "🎯 Service Management Commands:"
echo "   Start:   sudo systemctl start llm-job-processor"
echo "   Stop:    sudo systemctl stop llm-job-processor"
echo "   Restart: sudo systemctl restart llm-job-processor"
echo "   Status:  sudo systemctl status llm-job-processor"
echo "   Logs:    sudo journalctl -u llm-job-processor -f"
echo ""
echo "🔧 The auto processor will now:"
echo "   ✓ Automatically process pending jobs every 30 seconds"
echo "   ✓ Fix stuck jobs automatically"
echo "   ✓ Retry failed jobs (up to 3 attempts)"
echo "   ✓ Start automatically on system boot"
echo "   ✓ Restart automatically if it crashes"
echo ""
echo "📊 Monitor the dashboard at: http://your-domain/admin/eval/llmjob/dashboard/"
