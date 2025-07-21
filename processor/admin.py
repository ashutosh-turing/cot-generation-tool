from django.contrib import admin
from .models import AnalysisResult, LLMModel, Prompt

class AnalysisResultAdmin(admin.ModelAdmin):
    readonly_fields = ('timestamp', 'file_name', 'analysis', 'model', 'prompt')
    list_display = ('file_name', 'user','analysis','model', 'timestamp')
    list_filter = ('user', 'model', 'prompt')
    search_fields = ('file_name', 'analysis')

admin.site.register(AnalysisResult, AnalysisResultAdmin)
admin.site.register(LLMModel)
admin.site.register(Prompt)
