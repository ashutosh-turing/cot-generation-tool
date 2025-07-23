from django.db import models
import uuid
from django.contrib.auth.models import User
from django.utils import timezone

class LLMModel(models.Model):
    PROVIDER_CHOICES = [
        ('openai', 'OpenAI'),
        ('anthropic', 'Anthropic'),
        ('gemini', 'Google Gemini'),
    ]

    name = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='openai')
    api_key = models.CharField(max_length=255, blank=True, help_text="API key for this model's provider. If blank, will use environment variable.")
    description = models.TextField(blank=True, null=True)
    temperature = models.FloatField(default=0.7)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"

class StreamAndSubject(models.Model):
    """
    Model representing a Stream and Subject category for system messages
    """
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Stream and Subject"
        verbose_name_plural = "Streams and Subjects"

class Prompt(models.Model):
    prompt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt = models.TextField()
    instructions = models.TextField()
    username = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
  
    def __str__(self):
        return self.prompt   

class Response(models.Model):
    response_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE)
    response = models.TextField()
    formatted_response = models.TextField(blank=True, null=True, help_text="Response with formatting preserved")
    is_edited = models.BooleanField(default=False, help_text="Whether this response has been manually edited")
    edit_history = models.JSONField(default=list, blank=True, help_text="History of edits to this response")
    username = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.response
    
    def save_edit(self, new_content, editor=None):
        """
        Save an edited version of the response and track edit history
        
        Args:
            new_content (str): The new edited content
            editor (User, optional): The user making the edit
        """
        # Store the previous version in history
        history_entry = {
            'previous_content': self.response,
            'edited_at': timezone.now().isoformat(),
            'editor': editor.username if editor else None
        }
        
        # Update the edit history
        if isinstance(self.edit_history, list):
            self.edit_history.append(history_entry)
        else:
            self.edit_history = [history_entry]
        
        # Update the response content
        self.response = new_content
        # Also update the formatted_response field if it's not already set
        if not self.formatted_response:
            self.formatted_response = new_content
        self.is_edited = True
        self.save()
        
        return True
    

class Validation(models.Model):
    validation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    validation = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    

class Coherence(models.Model):
    coherence_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text = models.TextField()
    response = models.TextField()
    username = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Coherence analysis by {self.username} on {self.created_at}"

class ModelEvaluationHistory(models.Model):
    evaluation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_name = models.CharField(max_length=100)
    prompt = models.TextField()
    system_instructions = models.TextField(blank=True)
    temperature = models.FloatField(default=0.7)
    max_tokens = models.IntegerField(default=2048)
    evaluation_metrics = models.JSONField(default=dict)
    response = models.TextField()
    formatted_response = models.TextField(blank=True, null=True, help_text="Response with formatting preserved")
    is_edited = models.BooleanField(default=False, help_text="Whether this response has been manually edited")
    edit_history = models.JSONField(default=list, blank=True, help_text="History of edits to this response")
    username = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.model_name} evaluation by {self.username} on {self.created_at}"
    
    def save_edit(self, new_content, editor=None):
        """
        Save an edited version of the response and track edit history
        
        Args:
            new_content (str): The new edited content
            editor (User, optional): The user making the edit
        """
        # Store the previous version in history
        history_entry = {
            'previous_content': self.response,
            'edited_at': timezone.now().isoformat(),
            'editor': editor.username if editor else None
        }
        
        # Update the edit history
        if isinstance(self.edit_history, list):
            self.edit_history.append(history_entry)
        else:
            self.edit_history = [history_entry]
        
        # Update the response content
        self.response = new_content
        self.formatted_response = new_content
        self.is_edited = True
        self.save()
        
        return True

class SystemMessage(models.Model):
    """Model to store system messages/instructions for the AI model."""
    name = models.CharField(max_length=100, unique=True, help_text="A short name to identify this system message (e.g., 'Code Assistant', 'Helpful Chatbot').")
    content = models.TextField(help_text="The full system message content.")
    is_default = models.BooleanField(default=False, help_text="Mark as true if this is a pre-defined, default message selectable by users.")
    category = models.ForeignKey(
        StreamAndSubject, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='system_messages'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name'] # Order alphabetically by name by default

class TaskSyncConfig(models.Model):
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name="sync_configs", help_text="Project this sync config belongs to")
    sheet_url = models.URLField("Sheet/Data Source URL")
    sync_interval_minutes = models.PositiveIntegerField(default=60, help_text="How often to sync (in minutes)")
    primary_key_column = models.CharField(max_length=100, default="question_id", help_text="Column name to use as the unique identifier for tasks")
    scraping_needed = models.BooleanField(default=False, help_text="Whether scraping is needed for this project")
    link_column = models.CharField(max_length=100, blank=True, null=True, help_text="Column name containing the link to scrape (if scraping is needed)")
    column_mapping = models.JSONField(default=dict, blank=True, help_text="Map logical fields to sheet columns, e.g. {'prompt': 'Task Prompt'}")
    field_types = models.JSONField(default=dict, blank=True, help_text="Define field types for display, e.g. {'status': 'badge', 'link': 'url', 'date': 'datetime'}")
    display_config = models.JSONField(default=dict, blank=True, help_text="Display configuration for fields, e.g. column order, visibility, labels")
    sync_mode = models.CharField(
        max_length=50,
        choices=[
            ("prompt_in_sheet", "Prompt in Sheet"),
            ("scraping", "Scraping"),
            ("custom", "Custom")
        ],
        default="prompt_in_sheet",
        help_text="How to sync tasks for this project"
    )
    sheet_tab = models.CharField(max_length=100, blank=True, null=True, help_text="Sheet tab/range name (optional)")
    last_synced = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True, help_text="Whether this sync configuration is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        project_str = f"{self.project.code} - " if self.project else ""
        return f"{project_str}Sync: {self.sheet_url} every {self.sync_interval_minutes} min"
    
    def get_display_fields(self):
        """Get ordered list of fields to display based on display_config"""
        if self.display_config and 'field_order' in self.display_config:
            return self.display_config['field_order']
        elif self.column_mapping:
            # Default order: primary key first, then mapped fields
            fields = [self.primary_key_column]
            for logical_field in self.column_mapping.keys():
                if logical_field != self.primary_key_column and logical_field not in fields:
                    fields.append(logical_field)
            return fields
        else:
            # Fallback to model fields
            return ['question_id', 'problem_link', 'response_links', 'completed']
    
    def get_field_type(self, field_name):
        """Get the display type for a field"""
        return self.field_types.get(field_name, 'text')
    
    def get_field_label(self, field_name):
        """Get the display label for a field"""
        if self.display_config and 'field_labels' in self.display_config:
            return self.display_config['field_labels'].get(field_name, field_name.replace('_', ' ').title())
        return field_name.replace('_', ' ').title()

class TaskSyncHistory(models.Model):
    config = models.ForeignKey(TaskSyncConfig, on_delete=models.CASCADE, related_name="history")
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[("success", "Success"), ("failure", "Failure")])
    summary = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)
    updated_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    deleted_count = models.PositiveIntegerField(default=0)
    sync_type = models.CharField(max_length=10, choices=[("manual", "Manual"), ("auto", "Auto")], default="manual")
    synced_by = models.CharField(max_length=255, default="system")

    def __str__(self):
        return f"{self.timestamp} - {self.status} - {self.summary}"

class Project(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.code

class TrainerTask(models.Model):
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    reviewer = models.CharField(max_length=255, blank=True, null=True)
    developer = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    raw_prompt = models.TextField(blank=True, null=True)
    response_links = models.TextField(blank=True, null=True)
    rating = models.CharField(max_length=50, blank=True, null=True)
    level_of_difficulty = models.CharField(max_length=50, blank=True, null=True)
    question_id = models.CharField(max_length=100, blank=True, null=True)
    problem_link = models.URLField(blank=True, null=True)
    labelling_tool_id_link = models.CharField(max_length=255, blank=True, null=True)
    completed = models.CharField(max_length=50, blank=True, null=True)
    count = models.CharField(max_length=50, blank=True, null=True)
    delivered = models.CharField(max_length=50, blank=True, null=True)
    screenshot_drive_link = models.CharField(max_length=255, blank=True, null=True)
    exported_batch = models.CharField(max_length=255, blank=True, null=True)
    codeforces_submission_id = models.CharField(max_length=255, blank=True, null=True)
    plagiarism = models.CharField(max_length=255, blank=True, null=True)
    review_doc = models.CharField(max_length=255, blank=True, null=True)
    dynamic_fields = models.JSONField(default=dict, blank=True, help_text="Store additional fields from sheets that don't map to model fields")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.question_id} - {self.title}"
    
    def get_field_value(self, field_name):
        """Get value for a field, checking both model fields and dynamic fields"""
        # First check if it's a model field
        if hasattr(self, field_name):
            return getattr(self, field_name)
        # Then check dynamic fields
        return self.dynamic_fields.get(field_name, '')
    
    def set_field_value(self, field_name, value):
        """Set value for a field, using model field if exists, otherwise dynamic field"""
        if hasattr(self, field_name) and field_name != 'dynamic_fields':
            # Special handling for foreign key fields
            if field_name == 'project' and isinstance(value, str):
                # Don't set project field from string, it should be set separately
                if not self.dynamic_fields:
                    self.dynamic_fields = {}
                self.dynamic_fields[field_name] = value
            else:
                setattr(self, field_name, value)
        else:
            if not self.dynamic_fields:
                self.dynamic_fields = {}
            self.dynamic_fields[field_name] = value

class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preference')
    streams_and_subjects = models.ManyToManyField(StreamAndSubject, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"


class LLMJob(models.Model):
    """Model to track LLM processing jobs submitted via Pub/Sub"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    JOB_TYPE_CHOICES = [
        ('trainer_question_analysis', 'Trainer Question Analysis'),
        ('review_colab', 'Review Colab'),
        ('general_llm_request', 'General LLM Request'),
    ]
    
    job_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, null=True, blank=True)
    
    # Input data
    input_data = models.JSONField(default=dict, help_text="Input parameters for the job")
    
    # Results
    result_data = models.JSONField(default=dict, blank=True, help_text="Output results from the job")
    error_message = models.TextField(blank=True, null=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Additional fields for specific job types
    question_id = models.CharField(max_length=100, blank=True, null=True)
    
    def __str__(self):
        return f"{self.job_type} - {self.job_id} ({self.status})"
    
    def mark_processing(self):
        """Mark job as processing"""
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save()
    
    def mark_completed(self, result_data):
        """Mark job as completed with results"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.result_data = result_data
        self.save()
    
    def mark_failed(self, error_message):
        """Mark job as failed with error message"""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save()
    
    @property
    def is_complete(self):
        """Check if job is complete (either completed or failed)"""
        return self.status in ['completed', 'failed']
    
    @property
    def processing_time(self):
        """Get processing time in seconds"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_id']),
            models.Index(fields=['status']),
            models.Index(fields=['user', 'created_at']),
        ]


class UserActivitySession(models.Model):
    """
    Privacy-first activity tracking for personal productivity insights.
    Tracks user engagement time on task-related pages for statistics only.
    """
    
    ACTIVITY_TYPE_CHOICES = [
        ('trainer_analysis', 'Trainer Question Analysis'),
        ('review_task', 'Task Review'),
        ('modal_playground', 'Modal Playground'),
        ('dashboard_view', 'Dashboard View'),
    ]
    
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_sessions')
    task = models.ForeignKey(TrainerTask, on_delete=models.CASCADE, null=True, blank=True, related_name='activity_sessions')
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPE_CHOICES)
    
    # Time tracking
    session_start = models.DateTimeField(auto_now_add=True)
    session_end = models.DateTimeField(null=True, blank=True)
    focus_time_minutes = models.PositiveIntegerField(default=0, help_text="Actual engaged time in minutes")
    total_time_minutes = models.PositiveIntegerField(default=0, help_text="Total session time in minutes")
    
    # Engagement metrics (for quality scoring)
    page_interactions = models.PositiveIntegerField(default=0, help_text="Number of clicks, scrolls, etc.")
    llm_queries_count = models.PositiveIntegerField(default=0, help_text="Number of LLM queries in this session")
    
    # Privacy-friendly metadata
    activity_data = models.JSONField(default=dict, blank=True, help_text="Aggregated activity metrics (no detailed tracking)")
    
    # Session management
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.activity_type} - {self.focus_time_minutes}min"
    
    def end_session(self):
        """End the current session and calculate total time"""
        if not self.session_end:
            self.session_end = timezone.now()
            self.total_time_minutes = int((self.session_end - self.session_start).total_seconds() / 60)
            self.is_active = False
            self.save()
    
    def add_interaction(self, interaction_type='general'):
        """Record a user interaction (click, scroll, etc.)"""
        self.page_interactions += 1
        if interaction_type == 'llm_query':
            self.llm_queries_count += 1
        self.save()
    
    @property
    def engagement_score(self):
        """Calculate engagement score based on interactions and time"""
        if self.total_time_minutes == 0:
            return 0
        # Simple engagement score: interactions per minute
        return min(self.page_interactions / max(self.total_time_minutes, 1), 10)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['activity_type', 'created_at']),
            models.Index(fields=['user', 'activity_type']),
        ]


class UserProductivityInsight(models.Model):
    """
    Aggregated productivity insights for users - privacy-first approach.
    Stores weekly/monthly summaries rather than detailed session data.
    """
    
    PERIOD_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    
    insight_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='productivity_insights')
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Aggregated metrics
    total_focus_time_minutes = models.PositiveIntegerField(default=0)
    total_sessions = models.PositiveIntegerField(default=0)
    tasks_analyzed = models.PositiveIntegerField(default=0)
    llm_queries_total = models.PositiveIntegerField(default=0)
    modal_playground_sessions = models.PositiveIntegerField(default=0)
    
    # Quality metrics
    average_session_length = models.FloatField(default=0.0)
    average_engagement_score = models.FloatField(default=0.0)
    
    # Activity breakdown
    activity_breakdown = models.JSONField(default=dict, help_text="Time spent by activity type")
    
    # Personal insights (generated, not tracked)
    insights_data = models.JSONField(default=dict, help_text="Personal productivity patterns and insights")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.period_type} - {self.period_start}"
    
    @classmethod
    def generate_weekly_insight(cls, user, week_start):
        """Generate weekly productivity insight for a user"""
        from datetime import timedelta
        
        week_end = week_start + timedelta(days=6)
        
        # Get all sessions for this week
        sessions = UserActivitySession.objects.filter(
            user=user,
            session_start__date__range=[week_start, week_end],
            session_end__isnull=False
        )
        
        # Calculate aggregated metrics
        total_focus_time = sum(s.focus_time_minutes for s in sessions)
        total_sessions = sessions.count()
        tasks_analyzed = sessions.filter(activity_type='trainer_analysis').count()
        llm_queries = sum(s.llm_queries_count for s in sessions)
        modal_sessions = sessions.filter(activity_type='modal_playground').count()
        
        avg_session_length = total_focus_time / max(total_sessions, 1)
        avg_engagement = sum(s.engagement_score for s in sessions) / max(total_sessions, 1)
        
        # Activity breakdown
        breakdown = {}
        for activity_type, _ in UserActivitySession.ACTIVITY_TYPE_CHOICES:
            activity_time = sum(
                s.focus_time_minutes for s in sessions.filter(activity_type=activity_type)
            )
            if activity_time > 0:
                breakdown[activity_type] = activity_time
        
        # Create or update insight
        insight, created = cls.objects.update_or_create(
            user=user,
            period_type='weekly',
            period_start=week_start,
            defaults={
                'period_end': week_end,
                'total_focus_time_minutes': total_focus_time,
                'total_sessions': total_sessions,
                'tasks_analyzed': tasks_analyzed,
                'llm_queries_total': llm_queries,
                'modal_playground_sessions': modal_sessions,
                'average_session_length': avg_session_length,
                'average_engagement_score': avg_engagement,
                'activity_breakdown': breakdown,
            }
        )
        
        return insight
    
    class Meta:
        ordering = ['-period_start']
        unique_together = ['user', 'period_type', 'period_start']
        indexes = [
            models.Index(fields=['user', 'period_type', 'period_start']),
        ]
