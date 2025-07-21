# Fix for Stuck AI Analysis Jobs on Server

## Problem Summary
Your AI analysis jobs (Gemini 2.5 Flash and GPT-4.1) are stuck in queue because:
1. The LLM job processing service is not running on the server
2. Pending jobs are missing the `model_id` field required by the processor

## Solution Steps

### Step 1: Upload the Fix Script
Upload the `fix_stuck_jobs.py` file to your server in the project root directory.

### Step 2: Run the Fix Script on Server
```bash
# SSH into your server and navigate to project directory
cd /path/to/your/project

# Run the fix script
python fix_stuck_jobs.py
```

This script will:
- Check if the LLM job processing service is running
- Show available models in your database
- Fix pending jobs by adding missing `model_id` fields
- Republish jobs to the Pub/Sub queue
- Provide restart instructions if needed

### Step 3: Start the LLM Job Processing Service (if not running)
If the script shows the service is not running, start it with one of these options:

**Option 1 - Start individual service:**
```bash
python manage.py process_llm_jobs &
```

**Option 2 - Start all services:**
```bash
python run_services.py --mode production
```

**Option 3 - Use deployment script:**
```bash
./deploy.sh
```

### Step 4: Verify the Fix
Check that services are running:
```bash
./check_services.sh
```

Monitor job progress:
```bash
python manage.py shell -c "from eval.models import LLMJob; print(f'Pending: {LLMJob.objects.filter(status=\"pending\").count()}, Processing: {LLMJob.objects.filter(status=\"processing\").count()}, Completed: {LLMJob.objects.filter(status=\"completed\").count()}, Failed: {LLMJob.objects.filter(status=\"failed\").count()}')"
```

### Step 5: Monitor Logs (Optional)
If you have log files set up, monitor the processing:
```bash
tail -f logs/llm_jobs_v2.log
```

## Expected Results
After running the fix:
1. Pending jobs should change status from "pending" to "processing" then "completed"
2. Your AI analysis interface should show results instead of "In queue..."
3. New jobs should process normally

## Troubleshooting

### If jobs still don't process:
1. Check Google Cloud Pub/Sub credentials are properly configured
2. Verify API keys are set for the models (Gemini, OpenAI)
3. Check network connectivity to AI provider APIs

### If service keeps stopping:
1. Check for memory/resource issues on server
2. Review error logs for specific failure reasons
3. Consider running services with a process manager like systemd or supervisor

## Files Created
- `fix_stuck_jobs.py` - Main fix script
- `republish_pending_jobs.py` - Simple republish script (backup)
- `SERVER_FIX_GUIDE.md` - This guide

## Contact
If you encounter issues, check the error messages from the fix script and ensure:
- Database connectivity is working
- Google Cloud credentials are properly set
- Required Python packages are installed
- Sufficient server resources are available
