#!/usr/bin/env python
"""
Complete fix for stuck AI analysis jobs on the server.
This script will:
1. Check service status
2. Fix pending jobs by adding missing model_id
3. Republish jobs to Pub/Sub
4. Provide instructions for restarting services
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coreproject.settings')
django.setup()

from eval.models import LLMJob, LLMModel
from eval.utils.pubsub import publish_message
import json
import subprocess

def check_service_status():
    """Check if the LLM job processing service is running"""
    print("🔍 Checking LLM job processing service status...")
    try:
        result = subprocess.run(['pgrep', '-f', 'process_llm_jobs'], 
                              capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"✅ LLM job processing service is running (PIDs: {', '.join(pids)})")
            return True
        else:
            print("❌ LLM job processing service is NOT running")
            return False
    except Exception as e:
        print(f"❌ Error checking service status: {e}")
        return False

def get_model_id_by_name(model_name):
    """Get model ID by model name"""
    try:
        model = LLMModel.objects.get(name=model_name)
        return model.id
    except LLMModel.DoesNotExist:
        print(f"⚠️  Model '{model_name}' not found in database")
        return None

def fix_pending_jobs():
    """Fix pending jobs by adding missing model_id and republishing"""
    
    pending_jobs = LLMJob.objects.filter(status='pending').order_by('created_at')
    
    print(f"📋 Found {pending_jobs.count()} pending jobs to fix")
    
    if pending_jobs.count() == 0:
        print("✅ No pending jobs found")
        return True
    
    success_count = 0
    
    for job in pending_jobs:
        print(f"\n🔧 Fixing job {job.job_id} ({job.job_type})")
        print(f"   Model: {job.model}")
        print(f"   Created: {job.created_at}")
        
        try:
            # Get the model ID
            model_id = None
            if job.model:
                model_id = job.model.id
                print(f"   Model ID: {model_id}")
            else:
                print("   ⚠️  No model assigned to job")
                continue
            
            # Reconstruct the message data with all required fields
            message_data = {
                "type": job.job_type,
                "job_id": str(job.job_id),
                "model_id": model_id,
                **job.input_data  # Include all the original input data
            }
            
            # Add job-type specific fields
            if job.job_type == "trainer_question_analysis":
                # Ensure required fields are present
                if 'user_id' not in message_data and job.user:
                    message_data['user_id'] = job.user.id
                if 'question_id' not in message_data and job.question_id:
                    message_data['question_id'] = job.question_id
            
            print(f"   📤 Publishing message with data: {list(message_data.keys())}")
            
            # Publish to Pub/Sub
            publish_message(message_data)
            print(f"   ✅ Successfully republished job {job.job_id}")
            success_count += 1
            
        except Exception as e:
            print(f"   ❌ Error fixing job {job.job_id}: {e}")
    
    print(f"\n📊 Summary: {success_count}/{pending_jobs.count()} jobs successfully republished")
    return success_count == pending_jobs.count()

def show_service_restart_instructions():
    """Show instructions for restarting services"""
    print("\n" + "="*60)
    print("🚀 SERVICE RESTART INSTRUCTIONS")
    print("="*60)
    print()
    print("If the LLM job processing service is not running, restart it with:")
    print()
    print("Option 1 - Start individual service:")
    print("  python manage.py process_llm_jobs &")
    print()
    print("Option 2 - Start all services:")
    print("  python run_services.py --mode production")
    print()
    print("Option 3 - Use deployment script:")
    print("  ./deploy.sh")
    print()
    print("To check service status:")
    print("  ./check_services.sh")
    print()
    print("To monitor logs:")
    print("  tail -f logs/llm_jobs_v2.log")
    print()

def main():
    print("🔧 FIXING STUCK AI ANALYSIS JOBS")
    print("="*50)
    
    # Step 1: Check service status
    service_running = check_service_status()
    
    # Step 2: Show available models
    print("\n📋 Available LLM Models:")
    models = LLMModel.objects.all()
    for model in models:
        print(f"   ID: {model.id}, Name: {model.name}, Provider: {model.provider}")
    
    # Step 3: Fix pending jobs
    print("\n" + "="*50)
    jobs_fixed = fix_pending_jobs()
    
    # Step 4: Show restart instructions if needed
    if not service_running:
        show_service_restart_instructions()
    
    # Step 5: Final status
    print("\n" + "="*50)
    print("🎯 FINAL STATUS")
    print("="*50)
    
    if jobs_fixed and service_running:
        print("✅ All jobs fixed and service is running!")
        print("   Jobs should start processing shortly.")
    elif jobs_fixed and not service_running:
        print("⚠️  Jobs fixed but service needs to be restarted.")
        print("   Please restart the LLM job processing service.")
    elif not jobs_fixed and service_running:
        print("⚠️  Service is running but some jobs couldn't be fixed.")
        print("   Check the error messages above.")
    else:
        print("❌ Jobs need fixing AND service needs to be restarted.")
        print("   Please fix jobs and restart the service.")
    
    print("\nTo monitor progress:")
    print("  python manage.py shell -c \"from eval.models import LLMJob; print(f'Pending: {LLMJob.objects.filter(status=\"pending\").count()}, Processing: {LLMJob.objects.filter(status=\"processing\").count()}, Completed: {LLMJob.objects.filter(status=\"completed\").count()}, Failed: {LLMJob.objects.filter(status=\"failed\").count()}')\"")

if __name__ == "__main__":
    main()
