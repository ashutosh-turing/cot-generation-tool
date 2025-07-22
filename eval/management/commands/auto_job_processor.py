import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from eval.models import LLMJob, LLMModel
from eval.utils.pubsub import publish_message
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Automatically process pending LLM jobs and monitor system health'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Check interval in seconds (default: 30)',
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=3,
            help='Maximum retries for failed jobs (default: 3)',
        )
        parser.add_argument(
            '--auto-fix-stuck',
            action='store_true',
            help='Automatically fix stuck jobs',
        )
        parser.add_argument(
            '--auto-retry-failed',
            action='store_true',
            help='Automatically retry failed jobs',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        max_retries = options['max_retries']
        auto_fix_stuck = options['auto_fix_stuck']
        auto_retry_failed = options['auto_retry_failed']
        
        self.stdout.write(
            self.style.SUCCESS(
                f'🤖 Starting Auto Job Processor (interval: {interval}s)'
            )
        )
        
        if auto_fix_stuck:
            self.stdout.write('  ✓ Auto-fix stuck jobs enabled')
        if auto_retry_failed:
            self.stdout.write(f'  ✓ Auto-retry failed jobs enabled (max: {max_retries})')
        
        self.stdout.write('  Press Ctrl+C to stop\n')
        
        try:
            while True:
                self.process_cycle(max_retries, auto_fix_stuck, auto_retry_failed)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\n🛑 Auto Job Processor stopped'))

    def process_cycle(self, max_retries, auto_fix_stuck, auto_retry_failed):
        """Run one processing cycle"""
        try:
            # 1. Process pending jobs
            self.process_pending_jobs()
            
            # 2. Fix stuck jobs if enabled
            if auto_fix_stuck:
                self.fix_stuck_jobs()
            
            # 3. Retry failed jobs if enabled
            if auto_retry_failed:
                self.retry_failed_jobs(max_retries)
            
            # 4. Show status summary
            self.show_status_summary()
            
        except Exception as e:
            logger.error(f"Error in processing cycle: {e}")
            self.stdout.write(self.style.ERROR(f'❌ Cycle error: {e}'))

    def process_pending_jobs(self):
        """Automatically process pending jobs by republishing them to Pub/Sub"""
        pending_jobs = LLMJob.objects.filter(status='pending').order_by('created_at')
        
        if not pending_jobs.exists():
            return
        
        processed_count = 0
        for job in pending_jobs[:10]:  # Process up to 10 jobs per cycle
            try:
                # Validate job has required data
                if not job.model or not job.model.is_active:
                    job.mark_failed("Model not available or inactive")
                    continue
                
                if not job.model.api_key:
                    job.mark_failed("Model API key not configured")
                    continue
                
                # Republish job to Pub/Sub for processing
                message_data = {
                    "type": job.job_type,
                    "job_id": str(job.job_id),
                    "user_id": job.user.id if job.user else None,
                    "model_id": job.model.id,
                    **job.input_data
                }
                
                success = publish_message(message_data)
                if success:
                    processed_count += 1
                    logger.info(f"Republished job {job.job_id} to Pub/Sub")
                else:
                    logger.error(f"Failed to republish job {job.job_id}")
                    
            except Exception as e:
                logger.error(f"Error processing job {job.job_id}: {e}")
                job.mark_failed(f"Auto-processor error: {str(e)}")
        
        if processed_count > 0:
            self.stdout.write(f'  📤 Processed {processed_count} pending jobs')

    def fix_stuck_jobs(self):
        """Fix jobs that have been processing for too long"""
        stuck_cutoff = timezone.now() - timedelta(minutes=30)
        stuck_jobs = LLMJob.objects.filter(
            status='processing',
            started_at__lt=stuck_cutoff
        )
        
        fixed_count = 0
        for job in stuck_jobs:
            duration = timezone.now() - job.started_at
            job.mark_failed(f"Job automatically cancelled after {duration} (auto-processor)")
            fixed_count += 1
            logger.info(f"Fixed stuck job {job.job_id} (duration: {duration})")
        
        if fixed_count > 0:
            self.stdout.write(f'  🔧 Fixed {fixed_count} stuck jobs')

    def retry_failed_jobs(self, max_retries):
        """Retry failed jobs that haven't exceeded retry limit"""
        # Get failed jobs that can be retried
        failed_jobs = LLMJob.objects.filter(
            status='failed',
            completed_at__gte=timezone.now() - timedelta(hours=1)  # Only recent failures
        )
        
        retried_count = 0
        for job in failed_jobs:
            # Check retry count in input_data
            retry_count = job.input_data.get('retry_count', 0)
            
            if retry_count < max_retries:
                # Check if failure is retryable
                if self.is_retryable_error(job.error_message):
                    # Update retry count
                    job.input_data['retry_count'] = retry_count + 1
                    
                    # Reset job status
                    job.status = 'pending'
                    job.started_at = None
                    job.completed_at = None
                    job.error_message = None
                    job.save()
                    
                    retried_count += 1
                    logger.info(f"Retrying job {job.job_id} (attempt {retry_count + 2})")
        
        if retried_count > 0:
            self.stdout.write(f'  🔄 Retried {retried_count} failed jobs')

    def is_retryable_error(self, error_message):
        """Determine if an error is worth retrying"""
        if not error_message:
            return True
        
        error_lower = error_message.lower()
        
        # Don't retry these errors
        non_retryable = [
            'api key',
            'authentication',
            'authorization',
            'invalid model',
            'model not found',
            'quota exceeded',
            'billing',
            'marked as failed by admin'
        ]
        
        for pattern in non_retryable:
            if pattern in error_lower:
                return False
        
        # Retry network/temporary errors
        retryable = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'rate limit',
            'service unavailable',
            'internal server error'
        ]
        
        for pattern in retryable:
            if pattern in error_lower:
                return True
        
        # Default: retry unknown errors
        return True

    def show_status_summary(self):
        """Show current system status"""
        from django.db.models import Count
        
        # Get job counts
        status_counts = dict(
            LLMJob.objects.values('status').annotate(count=Count('status')).values_list('status', 'count')
        )
        
        pending = status_counts.get('pending', 0)
        processing = status_counts.get('processing', 0)
        failed = status_counts.get('failed', 0)
        completed = status_counts.get('completed', 0)
        
        # Show summary with colors
        timestamp = timezone.now().strftime('%H:%M:%S')
        
        status_line = f'[{timestamp}] '
        if pending > 0:
            status_line += f'🟡 {pending} pending '
        if processing > 0:
            status_line += f'🔵 {processing} processing '
        if failed > 0:
            status_line += f'🔴 {failed} failed '
        if completed > 0:
            status_line += f'🟢 {completed} completed'
        
        self.stdout.write(status_line)
        
        # Show warnings
        if pending > 20:
            self.stdout.write(self.style.WARNING(f'  ⚠️  High pending queue: {pending} jobs'))
        
        if processing == 0 and pending > 0:
            self.stdout.write(self.style.WARNING('  ⚠️  No jobs processing but pending jobs exist'))

    def check_system_health(self):
        """Check overall system health"""
        issues = []
        
        # Check for models without API keys
        models_without_keys = LLMModel.objects.filter(is_active=True, api_key='').count()
        if models_without_keys > 0:
            issues.append(f'{models_without_keys} active models without API keys')
        
        # Check for old stuck jobs
        old_stuck = LLMJob.objects.filter(
            status='processing',
            started_at__lt=timezone.now() - timedelta(hours=1)
        ).count()
        if old_stuck > 0:
            issues.append(f'{old_stuck} jobs stuck for >1 hour')
        
        return issues
