import os
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q
from eval.models import LLMJob, LLMModel
from django.conf import settings


class Command(BaseCommand):
    help = 'Diagnose LLM job issues and provide system health information'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix-stuck',
            action='store_true',
            help='Automatically fix stuck jobs (mark long-running processing jobs as failed)',
        )
        parser.add_argument(
            '--cleanup-old',
            action='store_true',
            help='Clean up completed jobs older than 30 days',
        )
        parser.add_argument(
            '--show-errors',
            action='store_true',
            help='Show detailed error messages for failed jobs',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== LLM Job Diagnostics ===\n'))
        
        # System Health Check
        self.check_system_health()
        
        # Job Statistics
        self.show_job_statistics()
        
        # Check for issues
        self.check_for_issues()
        
        # Show error details if requested
        if options['show_errors']:
            self.show_error_details()
        
        # Fix stuck jobs if requested
        if options['fix_stuck']:
            self.fix_stuck_jobs()
        
        # Cleanup old jobs if requested
        if options['cleanup_old']:
            self.cleanup_old_jobs()

    def check_system_health(self):
        self.stdout.write(self.style.HTTP_INFO('System Health Check:'))
        
        # Check Google Cloud credentials
        try:
            service_account_file = getattr(settings, 'SERVICE_ACCOUNT_FILE', None)
            if service_account_file and os.path.exists(service_account_file):
                self.stdout.write(f'  ✓ Service account file found: {service_account_file}')
            else:
                self.stdout.write(self.style.WARNING(f'  ⚠ Service account file not found or not configured'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ Error checking service account: {e}'))
        
        # Check Pub/Sub configuration
        try:
            project_id = getattr(settings, 'GOOGLE_CLOUD_PROJECT_ID', None)
            if project_id:
                self.stdout.write(f'  ✓ Google Cloud Project ID: {project_id}')
            else:
                self.stdout.write(self.style.WARNING('  ⚠ Google Cloud Project ID not configured'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ Error checking project ID: {e}'))
        
        # Check active models
        active_models = LLMModel.objects.filter(is_active=True).count()
        total_models = LLMModel.objects.count()
        self.stdout.write(f'  ✓ Active LLM Models: {active_models}/{total_models}')
        
        # Check for models without API keys
        models_without_keys = LLMModel.objects.filter(is_active=True, api_key='').count()
        if models_without_keys > 0:
            self.stdout.write(self.style.WARNING(f'  ⚠ {models_without_keys} active models without API keys'))
        
        self.stdout.write('')

    def show_job_statistics(self):
        self.stdout.write(self.style.HTTP_INFO('Job Statistics:'))
        
        # Overall stats
        total_jobs = LLMJob.objects.count()
        self.stdout.write(f'  Total Jobs: {total_jobs}')
        
        # Status breakdown
        status_counts = LLMJob.objects.values('status').annotate(count=Count('status'))
        for status_data in status_counts:
            status = status_data['status']
            count = status_data['count']
            percentage = (count / total_jobs * 100) if total_jobs > 0 else 0
            self.stdout.write(f'    {status.title()}: {count} ({percentage:.1f}%)')
        
        # Recent activity (last 24 hours)
        recent_cutoff = timezone.now() - timedelta(hours=24)
        recent_jobs = LLMJob.objects.filter(created_at__gte=recent_cutoff).count()
        self.stdout.write(f'  Jobs in last 24h: {recent_jobs}')
        
        # Job types
        type_counts = LLMJob.objects.values('job_type').annotate(count=Count('job_type'))
        self.stdout.write('  Job Types:')
        for type_data in type_counts:
            job_type = type_data['job_type']
            count = type_data['count']
            self.stdout.write(f'    {job_type}: {count}')
        
        self.stdout.write('')

    def check_for_issues(self):
        self.stdout.write(self.style.HTTP_INFO('Issue Detection:'))
        
        # Check for stuck jobs (processing for more than 30 minutes)
        stuck_cutoff = timezone.now() - timedelta(minutes=30)
        stuck_jobs = LLMJob.objects.filter(
            status='processing',
            started_at__lt=stuck_cutoff
        )
        
        if stuck_jobs.exists():
            self.stdout.write(self.style.WARNING(f'  ⚠ {stuck_jobs.count()} jobs stuck in processing state (>30 min)'))
            for job in stuck_jobs[:5]:  # Show first 5
                duration = timezone.now() - job.started_at
                self.stdout.write(f'    - {job.job_id} ({job.job_type}) - {duration}')
        else:
            self.stdout.write('  ✓ No stuck jobs found')
        
        # Check for high pending queue
        pending_jobs = LLMJob.objects.filter(status='pending').count()
        if pending_jobs > 50:
            self.stdout.write(self.style.WARNING(f'  ⚠ High number of pending jobs: {pending_jobs}'))
            self.stdout.write('    Consider checking if the job processor is running')
        elif pending_jobs > 10:
            self.stdout.write(self.style.WARNING(f'  ⚠ Moderate number of pending jobs: {pending_jobs}'))
        else:
            self.stdout.write(f'  ✓ Pending jobs queue looks healthy: {pending_jobs}')
        
        # Check for recent failures
        recent_failures = LLMJob.objects.filter(
            status='failed',
            completed_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        if recent_failures > 10:
            self.stdout.write(self.style.ERROR(f'  ✗ High failure rate: {recent_failures} failures in last hour'))
        elif recent_failures > 5:
            self.stdout.write(self.style.WARNING(f'  ⚠ Moderate failures: {recent_failures} failures in last hour'))
        else:
            self.stdout.write(f'  ✓ Low failure rate: {recent_failures} failures in last hour')
        
        # Check for jobs without users or models
        orphaned_jobs = LLMJob.objects.filter(Q(user__isnull=True) | Q(model__isnull=True)).count()
        if orphaned_jobs > 0:
            self.stdout.write(self.style.WARNING(f'  ⚠ {orphaned_jobs} jobs without user or model references'))
        
        self.stdout.write('')

    def show_error_details(self):
        self.stdout.write(self.style.HTTP_INFO('Recent Error Details:'))
        
        recent_failures = LLMJob.objects.filter(
            status='failed',
            completed_at__gte=timezone.now() - timedelta(hours=24)
        ).order_by('-completed_at')[:10]
        
        if not recent_failures.exists():
            self.stdout.write('  No recent failures found')
            return
        
        for job in recent_failures:
            self.stdout.write(f'  Job: {job.job_id} ({job.job_type})')
            self.stdout.write(f'    User: {job.user.username if job.user else "None"}')
            self.stdout.write(f'    Model: {job.model.name if job.model else "None"}')
            self.stdout.write(f'    Failed: {job.completed_at}')
            self.stdout.write(f'    Error: {job.error_message[:200]}...' if len(job.error_message or '') > 200 else f'    Error: {job.error_message}')
            self.stdout.write('')

    def fix_stuck_jobs(self):
        self.stdout.write(self.style.HTTP_INFO('Fixing Stuck Jobs:'))
        
        # Mark jobs processing for more than 30 minutes as failed
        stuck_cutoff = timezone.now() - timedelta(minutes=30)
        stuck_jobs = LLMJob.objects.filter(
            status='processing',
            started_at__lt=stuck_cutoff
        )
        
        count = 0
        for job in stuck_jobs:
            duration = timezone.now() - job.started_at
            job.mark_failed(f"Job automatically cancelled after {duration} (stuck job cleanup)")
            count += 1
            self.stdout.write(f'  Fixed: {job.job_id} (was processing for {duration})')
        
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f'  ✓ Fixed {count} stuck jobs'))
        else:
            self.stdout.write('  No stuck jobs to fix')
        
        self.stdout.write('')

    def cleanup_old_jobs(self):
        self.stdout.write(self.style.HTTP_INFO('Cleaning Up Old Jobs:'))
        
        # Delete completed jobs older than 30 days
        cutoff_date = timezone.now() - timedelta(days=30)
        old_jobs = LLMJob.objects.filter(
            status__in=['completed', 'failed'],
            completed_at__lt=cutoff_date
        )
        
        count = old_jobs.count()
        if count > 0:
            old_jobs.delete()
            self.stdout.write(self.style.SUCCESS(f'  ✓ Deleted {count} old jobs (>30 days)'))
        else:
            self.stdout.write('  No old jobs to clean up')
        
        self.stdout.write('')

    def style_status(self, status):
        """Return colored status text"""
        colors = {
            'pending': self.style.WARNING,
            'processing': self.style.HTTP_INFO,
            'completed': self.style.SUCCESS,
            'failed': self.style.ERROR,
        }
        return colors.get(status, lambda x: x)(status)
