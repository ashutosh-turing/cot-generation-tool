from django.contrib import admin
from .models import TrainerTask, TaskSyncConfig, TaskSyncHistory

@admin.register(TaskSyncConfig)
class TaskSyncConfigAdmin(admin.ModelAdmin):
    list_display = ("sheet_url", "sync_interval_minutes", "last_synced", "created_at", "updated_at")
    search_fields = ("sheet_url",)
    readonly_fields = ("last_synced", "created_at", "updated_at")

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
    list_display = ('name', 'provider', 'is_active', 'temperature')
    list_filter = ('provider', 'is_active')
    search_fields = ('name', 'description')

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

@admin.register(LLMJob)
class LLMJobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'job_type', 'status', 'user', 'model', 'question_id', 'created_at', 'processing_time')
    list_filter = ('job_type', 'status', 'model__provider', 'created_at')
    search_fields = ('job_id', 'question_id', 'user__username', 'model__name')
    readonly_fields = ('job_id', 'created_at', 'started_at', 'completed_at', 'processing_time')
    
    def processing_time(self, obj):
        return f"{obj.processing_time:.2f}s" if obj.processing_time else "-"
    processing_time.short_description = 'Processing Time'
    
    fieldsets = (
        ('Job Information', {
            'fields': ('job_id', 'job_type', 'status', 'user', 'model', 'question_id')
        }),
        ('Input Data', {
            'fields': ('input_data',),
            'classes': ('collapse',)
        }),
        ('Results', {
            'fields': ('result_data', 'error_message'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'started_at', 'completed_at', 'processing_time')
        }),
    )
