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
    last_synced = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True, help_text="Whether this sync configuration is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        project_str = f"{self.project.code} - " if self.project else ""
        return f"{project_str}Sync: {self.sheet_url} every {self.sync_interval_minutes} min"

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.question_id} - {self.title}"

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
