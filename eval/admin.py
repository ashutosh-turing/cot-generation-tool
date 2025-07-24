from django.contrib import admin
from .models import TrainerTask, TaskSyncConfig, TaskSyncHistory

@admin.register(TaskSyncConfig)
class TaskSyncConfigAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "sheet_url",
        "sync_interval_minutes",
        "primary_key_column",
        "scraping_needed",
        "link_column",
        "sync_mode",
        "sheet_tab",
        "last_synced",
        "is_active",
        "created_at",
        "updated_at"
    )
    search_fields = ("sheet_url", "project__code", "primary_key_column")
    readonly_fields = ("last_synced", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": (
                "project",
                "sheet_url",
                "sync_interval_minutes",
                "primary_key_column",
                "scraping_needed",
                "link_column",
                "sync_mode",
                "sheet_tab",
                "column_mapping",
                "is_active",
                "last_synced",
                "created_at",
                "updated_at"
            )
        }),
    )

@admin.register(TaskSyncHistory)
class TaskSyncHistoryAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "status", "summary", "updated_count", "created_count", "deleted_count")
    search_fields = ("summary", "details")
    list_filter = ("status", "timestamp")
    readonly_fields = ("timestamp",)

@admin.register(TrainerTask)
class TrainerTaskAdmin(admin.ModelAdmin):
    list_display = ("question_id", "title", "developer", "reviewer", "completed", "problem_link")
    search_fields = ("question_id", "title", "developer", "reviewer")
    list_filter = ("completed", "developer", "reviewer")
from eval.models import Prompt, Validation, Coherence, ModelEvaluationHistory, LLMModel, LLMJob
from .models import SystemMessage, StreamAndSubject, UserPreference

admin.site.register(Prompt)

@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'is_active', 'temperature', 'max_tokens')
    list_filter = ('provider', 'is_active')
    search_fields = ('name', 'description')
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'provider', 'description', 'is_active')
        }),
        ('Configuration', {
            'fields': ('api_key', 'temperature', 'max_tokens'),
            'description': 'Model configuration settings. Leave max_tokens blank to use provider defaults. Anthropic models require this field.'
        }),
    )

from .models import ProjectLLMModel

@admin.register(ProjectLLMModel)
class ProjectLLMModelAdmin(admin.ModelAdmin):
    list_display = ('project', 'llm_model', 'is_active', 'temperature', 'max_tokens', 'api_key')
    fieldsets = (
        ('Assignment', {
            'fields': ('project', 'llm_model', 'is_active')
        }),
        ('Overrides', {
            'fields': ('temperature', 'max_tokens', 'api_key', 'description')
        }),
    )
    list_filter = ('project', 'is_active', 'llm_model__provider')
    search_fields = ('project__code', 'llm_model__name')
    autocomplete_fields = ('project', 'llm_model')

class ValidationAdmin(admin.ModelAdmin):
    list_display = ('name', 'validation_id', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    readonly_fields = ('validation_id', 'created_at', 'updated_at')

class CoherenceAdmin(admin.ModelAdmin):
    list_display = ('username', 'created_at')
    list_filter = ('username',)
    search_fields = ('text', 'response')
    readonly_fields = ('coherence_id', 'created_at', 'updated_at')

class ModelEvaluationHistoryAdmin(admin.ModelAdmin):
    list_display = ('model_name', 'username', 'created_at', 'is_active')
    list_filter = ('model_name', 'username', 'is_active')
    search_fields = ('model_name', 'prompt', 'response')
    readonly_fields = ('evaluation_id', 'created_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('evaluation_id', 'model_name', 'username', 'is_active')
        }),
        ('Evaluation Details', {
            'fields': ('prompt', 'system_instructions', 'temperature', 'max_tokens')
        }),
        ('Results', {
            'fields': ('evaluation_metrics', 'response')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )

admin.site.register(Validation, ValidationAdmin)
admin.site.register(Coherence, CoherenceAdmin)
admin.site.register(ModelEvaluationHistory, ModelEvaluationHistoryAdmin)

@admin.register(StreamAndSubject)
class StreamAndSubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(SystemMessage)
class SystemMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_default', 'created_at', 'updated_at')
    list_filter = ('is_default', 'category')
    search_fields = ('name', 'content')

class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_streams_and_subjects', 'updated_at')
    search_fields = ('user__username',)
    readonly_fields = ('updated_at',)

    def get_streams_and_subjects(self, obj):
        return ", ".join([s.name for s in obj.streams_and_subjects.all()])
    get_streams_and_subjects.short_description = 'Streams and Subjects'

admin.site.register(UserPreference, UserPreferenceAdmin)

from .models import ProjectCriteria, Project

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    search_fields = ('code', 'name')
    list_display = ('code', 'name', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    ordering = ('code',)

@admin.register(ProjectCriteria)
class ProjectCriteriaAdmin(admin.ModelAdmin):
    list_display = ('project', 'validation', 'is_enabled', 'priority', 'created_at')
    list_filter = ('project', 'is_enabled', 'validation__is_active')
    search_fields = ('project__code', 'project__name', 'validation__name')
    list_editable = ('is_enabled', 'priority')
    ordering = ('project__code', 'priority', 'validation__name')
    
    fieldsets = (
        ('Configuration', {
            'fields': ('project', 'validation', 'is_enabled', 'priority')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('project', 'validation')

@admin.register(LLMJob)
class LLMJobAdmin(admin.ModelAdmin):
    list_display = ('job_id_short', 'job_type', 'status_colored', 'user', 'model', 'question_id', 'created_at', 'processing_time_formatted', 'actions_column')
    list_filter = ('job_type', 'status', 'model__provider', 'model', 'created_at', 'user')
    search_fields = ('job_id', 'question_id', 'user__username', 'model__name', 'error_message')
    readonly_fields = ('job_id', 'created_at', 'started_at', 'completed_at', 'processing_time_formatted', 'job_age')
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = ['retry_failed_jobs', 'cancel_stuck_jobs', 'mark_as_failed']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'model')
    
    def job_id_short(self, obj):
        return str(obj.job_id)[:8] + "..."
    job_id_short.short_description = 'Job ID'
    
    def status_colored(self, obj):
        from django.utils.safestring import mark_safe
        colors = {
            'pending': '#fbbf24',  # yellow
            'processing': '#3b82f6',  # blue
            'completed': '#10b981',  # green
            'failed': '#ef4444',  # red
        }
        color = colors.get(obj.status, '#6b7280')
        return mark_safe(f'<span style="color: {color}; font-weight: bold;">●</span> {obj.get_status_display()}')
    status_colored.short_description = 'Status'
    
    def processing_time_formatted(self, obj):
        if obj.processing_time:
            return f"{obj.processing_time:.2f}s"
        elif obj.status == 'processing' and obj.started_at:
            from django.utils import timezone
            current_time = (timezone.now() - obj.started_at).total_seconds()
            return f"{current_time:.2f}s (ongoing)"
        return "-"
    processing_time_formatted.short_description = 'Processing Time'
    
    def job_age(self, obj):
        from django.utils import timezone
        age = timezone.now() - obj.created_at
        if age.days > 0:
            return f"{age.days}d {age.seconds//3600}h"
        elif age.seconds > 3600:
            return f"{age.seconds//3600}h {(age.seconds%3600)//60}m"
        else:
            return f"{age.seconds//60}m {age.seconds%60}s"
    job_age.short_description = 'Age'
    
    def actions_column(self, obj):
        from django.utils.safestring import mark_safe
        actions = []
        if obj.status == 'failed':
            actions.append(f'<a href="/admin/eval/llmjob/{obj.job_id}/retry/" style="color: #3b82f6;">Retry</a>')
        if obj.status == 'processing':
            actions.append(f'<a href="/admin/eval/llmjob/{obj.job_id}/cancel/" style="color: #ef4444;">Cancel</a>')
        return mark_safe(' | '.join(actions)) if actions else '-'
    actions_column.short_description = 'Actions'
    
    def retry_failed_jobs(self, request, queryset):
        failed_jobs = queryset.filter(status='failed')
        count = 0
        for job in failed_jobs:
            # Reset job status to pending for retry
            job.status = 'pending'
            job.started_at = None
            job.completed_at = None
            job.error_message = None
            job.save()
            count += 1
        self.message_user(request, f"Successfully queued {count} jobs for retry.")
    retry_failed_jobs.short_description = "Retry selected failed jobs"
    
    def cancel_stuck_jobs(self, request, queryset):
        stuck_jobs = queryset.filter(status='processing')
        count = 0
        for job in stuck_jobs:
            job.mark_failed("Job cancelled by admin")
            count += 1
        self.message_user(request, f"Successfully cancelled {count} stuck jobs.")
    cancel_stuck_jobs.short_description = "Cancel selected processing jobs"
    
    def mark_as_failed(self, request, queryset):
        pending_jobs = queryset.filter(status='pending')
        count = 0
        for job in pending_jobs:
            job.mark_failed("Marked as failed by admin")
            count += 1
        self.message_user(request, f"Successfully marked {count} jobs as failed.")
    mark_as_failed.short_description = "Mark selected pending jobs as failed"
    
    fieldsets = (
        ('Job Information', {
            'fields': ('job_id', 'job_type', 'status', 'user', 'model', 'question_id')
        }),
        ('Timing Information', {
            'fields': ('created_at', 'started_at', 'completed_at', 'processing_time_formatted', 'job_age')
        }),
        ('Input Data', {
            'fields': ('input_data',),
            'classes': ('collapse',)
        }),
        ('Results', {
            'fields': ('result_data', 'error_message'),
            'classes': ('collapse',)
        }),
    )
    
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_site.admin_view(self.job_dashboard_view), name='eval_llmjob_dashboard'),
            path('<uuid:job_id>/retry/', self.admin_site.admin_view(self.retry_job_view), name='eval_llmjob_retry'),
            path('<uuid:job_id>/cancel/', self.admin_site.admin_view(self.cancel_job_view), name='eval_llmjob_cancel'),
        ]
        return custom_urls + urls
    
    def job_dashboard_view(self, request):
        from django.shortcuts import render
        from django.db.models import Count, Q
        from django.utils import timezone
        from datetime import timedelta
        
        # Get statistics
        total_jobs = LLMJob.objects.count()
        status_counts = LLMJob.objects.values('status').annotate(count=Count('status'))
        
        # Recent jobs (last 24 hours)
        recent_jobs = LLMJob.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        # Jobs by type
        type_counts = LLMJob.objects.values('job_type').annotate(count=Count('job_type'))
        
        # Failed jobs with errors
        failed_jobs = LLMJob.objects.filter(status='failed').order_by('-created_at')[:10]
        
        # Long running jobs (processing for more than 10 minutes)
        long_running = LLMJob.objects.filter(
            status='processing',
            started_at__lt=timezone.now() - timedelta(minutes=10)
        ).order_by('started_at')
        
        context = {
            'title': 'LLM Job Dashboard',
            'total_jobs': total_jobs,
            'status_counts': {item['status']: item['count'] for item in status_counts},
            'recent_jobs': recent_jobs,
            'type_counts': {item['job_type']: item['count'] for item in type_counts},
            'failed_jobs': failed_jobs,
            'long_running_jobs': long_running,
        }
        
        return render(request, 'admin/eval/llmjob/dashboard.html', context)
    
    def retry_job_view(self, request, job_id):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        
        job = get_object_or_404(LLMJob, job_id=job_id)
        if job.status == 'failed':
            job.status = 'pending'
            job.started_at = None
            job.completed_at = None
            job.error_message = None
            job.save()
            messages.success(request, f"Job {job_id} has been queued for retry.")
        else:
            messages.error(request, f"Job {job_id} cannot be retried (current status: {job.status}).")
        
        return redirect('admin:eval_llmjob_changelist')
    
    def cancel_job_view(self, request, job_id):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        
        job = get_object_or_404(LLMJob, job_id=job_id)
        if job.status == 'processing':
            job.mark_failed("Job cancelled by admin")
            messages.success(request, f"Job {job_id} has been cancelled.")
        else:
            messages.error(request, f"Job {job_id} cannot be cancelled (current status: {job.status}).")
        
        return redirect('admin:eval_llmjob_changelist')
