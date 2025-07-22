#!/bin/bash

# LLM Job Monitoring - Quick Start Script
# This script helps you quickly access the LLM job monitoring interface

echo "🚀 LLM Job Monitoring System - Quick Start"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: manage.py not found. Please run this script from the Django project root."
    exit 1
fi

# Run system checks
echo "🔍 Running system checks..."
python manage.py check --deploy 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ System checks passed"
else
    echo "⚠️  System checks found issues (see above)"
fi

# Run LLM job diagnostics
echo ""
echo "🔧 Running LLM job diagnostics..."
python manage.py llm_job_diagnostics

echo ""
echo "🤖 Starting Auto Job Processor in background..."
# Start the auto job processor in background
python manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed &
AUTO_PROCESSOR_PID=$!

echo "✅ Auto Job Processor started (PID: $AUTO_PROCESSOR_PID)"
echo ""
echo "🌐 Starting Django development server..."
echo ""
echo "📊 Access the LLM Job Monitoring Dashboard at:"
echo "   http://127.0.0.1:8000/admin/eval/llmjob/dashboard/"
echo ""
echo "📋 Access the LLM Job List at:"
echo "   http://127.0.0.1:8000/admin/eval/llmjob/"
echo ""
echo "🔧 Access LLM Models Management at:"
echo "   http://127.0.0.1:8000/admin/eval/llmmodel/"
echo ""
echo "🤖 Auto Job Processor is running automatically:"
echo "   - Processes pending jobs every 30 seconds"
echo "   - Automatically fixes stuck jobs"
echo "   - Retries failed jobs (up to 3 attempts)"
echo ""
echo "Press Ctrl+C to stop both services"
echo "=================================="

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    if kill -0 $AUTO_PROCESSOR_PID 2>/dev/null; then
        kill $AUTO_PROCESSOR_PID
        echo "✅ Auto Job Processor stopped"
    fi
    exit 0
}

# Set trap to cleanup on exit
trap cleanup SIGINT SIGTERM

# Start the development server
python manage.py runserver 127.0.0.1:8000
