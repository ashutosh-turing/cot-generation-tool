from django.db import models
from django.contrib.auth.models import User

class LLMModel(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    temperature = models.FloatField(blank=True, null=True)
    is_active = models.BooleanField(default=True)


    def __str__(self):
        return self.name

class Prompt(models.Model):
    name = models.CharField(max_length=255, unique=True)
    instructions = models.TextField()
    system_message = models.TextField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class AnalysisResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=255)
    analysis = models.TextField()
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE)
    prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.file_name} - {self.timestamp}"
