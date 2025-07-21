# processor/forms.py
from django import forms
from .models import LLMModel, Prompt

class CSVUploadForm(forms.Form):
    file = forms.FileField(
        label='Select a CSV file',
        widget=forms.FileInput(attrs={'accept': '.csv'}),
        help_text='CSV file should contain a ColabLinks column with Google Colab URLs'
    )
    model = forms.ModelChoiceField(
        queryset=LLMModel.objects.all(),
        label="LLM Model",
        help_text="Select the LLM model to use for analysis"
    )
    prompt = forms.ModelChoiceField(
        queryset=Prompt.objects.all(),
        label="Prompt",
        help_text="Select the prompt to use for analysis"
    )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if not file.name.endswith('.csv'):
                raise forms.ValidationError('File must be a CSV file')
        return file
