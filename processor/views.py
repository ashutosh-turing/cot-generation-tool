from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.http import StreamingHttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
import json
import queue
from .forms import CSVUploadForm
from .utils import process_csv_and_evaluate
from .logger import log_queue, log_message
from openai import OpenAI
import os
import shutil
from .models import AnalysisResult
from django.contrib.auth.decorators import login_required

class ProcessingStep:
    def __init__(self, title, status, details=None, filename=None):
        self.title = title
        self.status = status
        self.details = details
        self.filename = filename  # Make sure this is set when creating steps

@csrf_exempt
def get_logs(request):
    def event_stream():
        print("Starting event stream") # Debug print
        while True:
            try:
                # Shorter timeout to be more responsive
                log_data = log_queue.get(timeout=0.5)
                if log_data and 'message' in log_data and 'timestamp' in log_data:
                    print(f"Sending log: {log_data}") # Debug print
                    yield f"data: {json.dumps(log_data)}\n\n"
                    # Flush the output buffer
                    if hasattr(response, 'flush'):
                        response.flush()
            except queue.Empty:
                # Send heartbeat more frequently
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                if hasattr(response, 'flush'):
                    response.flush()

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    response['Access-Control-Allow-Origin'] = '*'  # For development only
    return response

@login_required
def upload_csv(request):
    analysis_results = []
    processing_steps = []
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Check if the user confirmed deletion
            if request.POST.get('delete_confirmed') == 'true':
                # Call delete_create_temp_files to clear the directory
                delete_create_temp_files(request)
                # Redirect to the upload_csv page after deletion
                return HttpResponseRedirect(reverse('upload_csv'))
            else:
                try:
                    log_message("Starting file processing...")
                    csv_file = form.cleaned_data['file']
                    model = form.cleaned_data['model']
                    prompt = form.cleaned_data['prompt']
                    log_message(f"Processing file: {csv_file.name}")
                    log_message(f"Using model: {model.name}")
                    log_message(f"Prompt: {prompt.name}")
                    log_message("Validating CSV format...")
                    log_message("Reading CSV contents...")
                    log_message("Preparing data for LLM evaluation...")
                    log_message("Sending data to OpenAI API...")
                    log_message("Processing API responses...")
                    log_message("Generating final analysis...")
                    
                    # Check if using DeepSeek model
                    if 'deepseek' in model.name.lower():
                        log_message(f"Using DeepSeek model: {model.name}")
                    else:
                        log_message(f"Using OpenAI model: {model.name}")
                    
                    analysis_results, processing_steps = process_csv_and_evaluate(
                        csv_file, 
                        settings.OPENAI_API_KEY,
                        model,
                        prompt,
                        request
                    )
                    
                    if analysis_results:
                        log_message("✅ Processing completed successfully!")
                        messages.success(request, 'Files processed successfully!')

                        # Save results to the database
                        for result in analysis_results:
                            AnalysisResult.objects.create(
                                user=request.user,
                                file_name=result['file_name'],
                                analysis=result['analysis'],
                                model=model,
                                prompt=prompt
                            )
                    else:
                        log_message("⚠️ No results were generated")
                        messages.warning(request, 'No results were generated from the processing.')
                except Exception as e:
                    error_msg = f'Error processing file: {str(e)}'
                    log_message(f"❌ Error: {error_msg}")
                    messages.error(request, error_msg)
        # If the form is not valid or it's a GET request, just render the form
        else:
            # Form is invalid, handle errors
            messages.error(request, 'Form is invalid. Please correct the errors below.');
            return render(request, 'processor/upload.html', {'form': form, 'results': analysis_results, 'processing_steps': processing_steps})
    else:
        form = CSVUploadForm()
    
    # Check if the directory exists and has files
    temp_dir = os.path.join(settings.BASE_DIR, 'processor', 'download_container', request.user.username)
    files_in_temp_dir = os.listdir(temp_dir) if os.path.exists(temp_dir) else []
    
    return render(request, 'processor/upload.html', {
        'form': form, 
        'results': analysis_results,
        'processing_steps': processing_steps,
        'has_temp_files': bool(files_in_temp_dir)
    })

def delete_create_temp_files(request):
    # Delete temporary files
    temp_dir = os.path.join(settings.BASE_DIR, 'processor', 'download_container', request.user.username)
    if os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)  # Recreate the directory
            log_message("Deleted and recreated temporary files directory")
            messages.success(request, 'Temporary files deleted successfully!')
        except Exception as e:
            log_message(f"Error deleting temporary files: {e}")
            messages.error(request, f'Error deleting temporary files: {e}')
    else:
        os.makedirs(temp_dir)  # Create the directory if it doesn't exist
        log_message("Created temporary files directory")
        messages.info(request, 'Temporary files directory created.')
    return #HttpResponseRedirect(reverse('upload_csv'))