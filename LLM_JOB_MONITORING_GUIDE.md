# LLM Job Monitoring System Guide

This guide explains how to use the enhanced LLM job monitoring system in the Django admin interface.

## Overview

The LLM job monitoring system provides comprehensive tracking and management of LLM processing jobs, including:

- Real-time job status monitoring
- Detailed error analysis
- Bulk job management actions
- System health diagnostics
- Performance analytics

## Features

### 1. Enhanced Admin Interface

#### Job List View (`/admin/eval/llmjob/`)
- **Color-coded status indicators**: Visual status representation with colored dots
- **Shortened Job IDs**: First 8 characters for better readability
- **Processing time tracking**: Shows current processing time for ongoing jobs
- **Job age calculation**: How long ago the job was created
- **Quick action links**: Direct retry/cancel links for applicable jobs
- **Advanced filtering**: Filter by status, job type, model, user, and date
- **Bulk actions**: Retry failed jobs, cancel stuck jobs, mark as failed

#### Dashboard View (`/admin/eval/llmjob/dashboard/`)
- **Status overview**: Visual cards showing job counts by status
- **Recent activity**: Jobs created in the last 24 hours
- **Job type breakdown**: Distribution of different job types
- **Failed job analysis**: Recent failures with error details
- **Long-running job detection**: Jobs processing for >10 minutes
- **System health indicators**: Queue health and processor status
- **Auto-refresh**: Updates every 30 seconds

### 2. Job Status Meanings

- **Pending** 🟡: Job is queued and waiting to be processed
- **Processing** 🔵: Job is currently being executed
- **Completed** 🟢: Job finished successfully
- **Failed** 🔴: Job encountered an error and stopped

### 3. Common Issues and Solutions

#### Jobs Stuck in Pending Status

**Possible Causes:**
1. Job processor not running
2. Google Cloud Pub/Sub subscription issues
3. Service account credentials problems
4. High queue backlog

**Solutions:**
1. Check if the job processor is running:
   ```bash
   python manage.py process_llm_jobs
   ```

2. Verify Google Cloud configuration:
   ```bash
   python manage.py llm_job_diagnostics
   ```

3. Check service account file exists and has proper permissions

#### Jobs Stuck in Processing Status

**Possible Causes:**
1. LLM API timeouts
2. Network connectivity issues
3. Invalid API keys
4. Model unavailability

**Solutions:**
1. Use the diagnostic command to identify stuck jobs:
   ```bash
   python manage.py llm_job_diagnostics --fix-stuck
   ```

2. Check model API keys in the admin interface
3. Review error logs for specific failure reasons

#### High Failure Rates

**Possible Causes:**
1. Invalid or expired API keys
2. Model quota exceeded
3. Malformed input data
4. Network issues

**Solutions:**
1. Review recent error details:
   ```bash
   python manage.py llm_job_diagnostics --show-errors
   ```

2. Update API keys for affected models
3. Check API usage quotas with providers

### 4. Management Commands

#### Diagnostic Command
```bash
# Basic diagnostics
python manage.py llm_job_diagnostics

# Show detailed error messages
python manage.py llm_job_diagnostics --show-errors

# Fix stuck jobs automatically
python manage.py llm_job_diagnostics --fix-stuck

# Clean up old completed jobs
python manage.py llm_job_diagnostics --cleanup-old

# Combine multiple options
python manage.py llm_job_diagnostics --show-errors --fix-stuck --cleanup-old
```

#### Job Processor
```bash
# Start the job processor (should run continuously)
python manage.py process_llm_jobs
```

### 5. Bulk Actions

#### Retry Failed Jobs
1. Go to `/admin/eval/llmjob/`
2. Filter for failed jobs: `?status__exact=failed`
3. Select jobs to retry
4. Choose "Retry selected failed jobs" from the action dropdown
5. Click "Go"

#### Cancel Stuck Jobs
1. Filter for processing jobs: `?status__exact=processing`
2. Select long-running jobs
3. Choose "Cancel selected processing jobs"
4. Click "Go"

### 6. Monitoring Best Practices

#### Daily Monitoring
1. Check the dashboard for overall system health
2. Review any failed jobs and their error messages
3. Monitor queue size (pending jobs)
4. Verify job processor is running

#### Weekly Maintenance
1. Run diagnostics with cleanup:
   ```bash
   python manage.py llm_job_diagnostics --cleanup-old --fix-stuck
   ```
2. Review job success rates by model
3. Check for any recurring error patterns

#### Monthly Review
1. Analyze job performance trends
2. Review and update API keys as needed
3. Optimize job processing based on usage patterns

### 7. API Integration

The system provides API endpoints for programmatic access:

```python
# Submit a new job
POST /api/llm/jobs/submit/

# Check job status
GET /api/llm/jobs/{job_id}/status/

# Get job results
GET /api/llm/jobs/{job_id}/result/

# List user jobs
GET /api/llm/jobs/
```

### 8. Troubleshooting

#### Dashboard Not Loading
- Check if the template files are in the correct location
- Verify admin URLs are properly configured
- Ensure user has admin permissions

#### Jobs Not Processing
1. Verify Google Cloud credentials:
   ```bash
   echo $GOOGLE_APPLICATION_CREDENTIALS
   ```

2. Check Pub/Sub subscription exists:
   ```bash
   python manage.py setup_pubsub
   ```

3. Test model connectivity:
   ```bash
   python manage.py shell
   >>> from eval.models import LLMModel
   >>> model = LLMModel.objects.filter(is_active=True).first()
   >>> print(model.api_key)  # Should not be empty
   ```

#### Performance Issues
- Monitor database query performance
- Consider adding indexes for frequently filtered fields
- Use database connection pooling for high-volume scenarios

### 9. Security Considerations

- API keys are stored encrypted in the database
- Admin access is restricted to authorized users
- Job data may contain sensitive information - ensure proper access controls
- Regular backup of job data is recommended

### 10. Support and Maintenance

For additional support:
1. Check the server logs for detailed error messages
2. Use the diagnostic command for system health checks
3. Monitor Google Cloud Pub/Sub metrics
4. Review Django admin logs for user actions

## Automatic Job Processing

### 🤖 Auto Job Processor
The system now includes an **automatic job processor** that eliminates the need for manual intervention:

```bash
# Start automatic processing (recommended)
python manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed

# Development mode with both services
./start_admin.sh

# Production setup
sudo ./setup_auto_processor.sh
```

**What it does automatically:**
- ✅ **Processes pending jobs** every 30 seconds
- ✅ **Fixes stuck jobs** (processing >30 minutes)
- ✅ **Retries failed jobs** (up to 3 attempts for retryable errors)
- ✅ **Validates job requirements** (model availability, API keys)
- ✅ **Real-time status monitoring** with colored output
- ✅ **Intelligent error handling** (distinguishes retryable vs permanent errors)

### Production Deployment
For production environments, use the systemd service:

```bash
# One-time setup (creates systemd service)
sudo ./setup_auto_processor.sh

# Service management
sudo systemctl start llm-job-processor    # Start
sudo systemctl stop llm-job-processor     # Stop
sudo systemctl restart llm-job-processor  # Restart
sudo systemctl status llm-job-processor   # Check status
sudo journalctl -u llm-job-processor -f   # View logs
```

## Quick Reference

| Action | URL/Command | Purpose |
|--------|-------------|---------|
| **Admin Interface** | | |
| Job List | `/admin/eval/llmjob/` | View and manage all jobs |
| Dashboard | `/admin/eval/llmjob/dashboard/` | System overview and analytics |
| Models | `/admin/eval/llmmodel/` | Manage LLM models and API keys |
| **Automatic Processing** | | |
| Auto Processor | `python manage.py auto_job_processor --auto-fix-stuck --auto-retry-failed` | **Automatic job processing** |
| Quick Start | `./start_admin.sh` | Start both admin and auto processor |
| Production Setup | `sudo ./setup_auto_processor.sh` | Install as system service |
| **Manual Tools** | | |
| Diagnostics | `python manage.py llm_job_diagnostics` | System health check |
| Legacy Processor | `python manage.py process_llm_jobs` | Manual job processor |

## Status Indicators

- 🟡 **Pending**: Waiting in queue
- 🔵 **Processing**: Currently running
- 🟢 **Completed**: Finished successfully  
- 🔴 **Failed**: Encountered error
- ⚠️ **Stuck**: Processing too long
- 📊 **Dashboard**: System overview available
