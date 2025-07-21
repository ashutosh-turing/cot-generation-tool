from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
from openai import OpenAI
from datetime import datetime
from .models import Validation, SystemMessage, StreamAndSubject, UserPreference
from .utils.sheets import fetch_trainer_tasks
import requests
from bs4 import BeautifulSoup
from processor.models import AnalysisResult
from eval.models import LLMModel
from .utils.analysis import analyze_reasoning_for_files  # consolidated function
import json, re, os 
from .models import Coherence
import time
import concurrent.futures
import threading
import uuid
import queue
import random
from .models import ModelEvaluationHistory
from django.utils import timezone
from django.contrib.auth.models import User

# Helper function to get user role
def get_user_role(user):
    """
    Get the role for a given user.
    Returns 'admin', 'pod_lead', or 'trainer'.
    Matches the logic in the user_group context processor.
    """
    if not user.is_authenticated:
        return None

    if user.is_superuser or user.is_staff or user.groups.filter(name='admin').exists():
        return 'admin'
    elif user.groups.filter(name='pod_lead').exists():
        return 'pod_lead'
    elif user.groups.filter(name='trainer').exists():
        return 'trainer'
    else:
        return None

# Decorator to restrict view access based on user role
def role_required(roles):
    """
    Decorator to restrict view access based on user role.
    Usage: @role_required(['admin', 'pod_lead'])
    """
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            user_role = get_user_role(request.user)
            if user_role in roles:
                return view_func(request, *args, **kwargs)
            else:
                messages.error(request, "You don't have permission to access this page.")
                return redirect('index')  # Redirect to home page
        return _wrapped_view
    return decorator


# Store model evaluation results
model_results = {}
model_results_queues = {}

def is_not_trainer(user):
    """
    Check if user should have access to non-trainer views.
    Admins and pod_leads have access regardless of trainer group membership.
    Only pure trainers (without admin/pod_lead roles) are restricted.
    """
    user_role = get_user_role(user)
    # Admins and pod_leads have access to all views
    if user_role in ['admin', 'pod_lead']:
        return True
    # Pure trainers are restricted
    return user_role != 'trainer'

# (removed duplicate import of LLMModel)

@login_required
def trainer_question_analysis(request, question_id):
    """
    View for trainer to analyze a specific question.
    - GET: Scrapes Codeforces for the problem statement and references, displays UI.
    - POST: Runs analysis and returns chain of thought as JSON.
    """
    import json as pyjson
    from django.utils.html import escape
    from django.http import JsonResponse

    # Helper to scrape Codeforces
    def scrape_codeforces(qid):
        print(qid)
        codeforces_url = f"https://codeforces.com/problemset/problem/{qid}"
        problem_title = ""
        problem_statement = ""
        references = []
        error = None
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            resp = requests.get(codeforces_url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("div", class_="title")
                if title_tag:
                    problem_title = title_tag.text.strip()
                statement_tag = soup.find("div", class_="problem-statement")
                if statement_tag:
                    problem_statement = statement_tag.text.strip()
                references = [a['href'] for a in statement_tag.find_all("a", href=True)] if statement_tag else []
            else:
                error = f"Failed to fetch problem from Codeforces (status {resp.status_code})"
        except Exception as e:
            error = f"Error scraping Codeforces: {str(e)}"
        return problem_title, problem_statement, references, error

    if request.method == "POST":
        # Handle AJAX analysis request for LLM analysis
        system_message = request.POST.get("system_message", "")
        additional_context = request.POST.get("additional_context", "")
        llm_model_ids = request.POST.getlist("llm_models")
        # Compose the prompt
        prompt = request.POST.get("prompt", "")
        # If prompt is not provided, use problem_statement from GET
        if not prompt:
            from .models import TrainerTask
            task = TrainerTask.objects.filter(question_id=question_id).first()
            if task:
                prompt = task.title or ""
        # Compose the full input for LLM
        full_input = f"{prompt}\n\nAdditional context:\n{additional_context}" if additional_context else prompt
        # Use the first selected LLM model, or a default
        model_obj = None
        if llm_model_ids:
            model_obj = LLMModel.objects.filter(id=llm_model_ids[0]).first()

        if not model_obj:
            return JsonResponse({"success": False, "error": "Please select at least one LLM model."})

        # Generate a unique job ID for this analysis request
        job_id = str(uuid.uuid4())
        
        # Publish a job for each selected model
        try:
            from .utils.pubsub import publish_message
            for model_id in llm_model_ids:
                data_to_publish = {
                    "type": "trainer_question_analysis",
                    "job_id": job_id,
                    "question_id": str(question_id),
                    "user_id": request.user.id,
                    "system_message": system_message,
                    "full_input": full_input,
                    "model_id": model_id,
                }
                publish_message(data_to_publish)
            
            return JsonResponse({
                "success": True,
                "job_id": job_id,
                "message": f"Your request for {len(llm_model_ids)} models has been queued."
            })
        except Exception as e:
            return JsonResponse({"success": False, "error": f"Failed to publish request: {str(e)}"})
    else:
        # GET: Render the analysis page
        from .models import TrainerTask
        task = TrainerTask.objects.filter(question_id=question_id).first()
        reference_data = []
        if task:
            problem_link = task.problem_link
            references = []
            if task.response_links:
                # Try to parse as a Python list, fallback to comma split
                import ast
                try:
                    links = ast.literal_eval(task.response_links)
                    if isinstance(links, list):
                        references = [str(link).strip().strip("'").strip('"') for link in links if str(link).strip()]
                    else:
                        references = [str(links).strip()]
                except Exception:
                    references = [link.strip().strip("'").strip('"') for link in task.response_links.split(",") if link.strip()]
            # Scrape the problem statement from the problem_link
            problem_title = ""
            problem_statement = ""
            problem_html = ""
            error = None
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                }
                resp = requests.get(problem_link, headers=headers)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    title_tag = soup.find("div", class_="title")
                    if title_tag:
                        problem_title = title_tag.text.strip()
                    statement_tag = soup.find("div", class_="problem-statement")
                    if statement_tag:
                        problem_statement = statement_tag.text.strip()
                        problem_html = str(statement_tag)
                else:
                    error = f"Failed to fetch problem from link (status {resp.status_code})"
            except Exception as e:
                error = f"Error scraping problem link: {str(e)}"
            # Always define reference_data
            if references:
                for ref in references:
                    reference_data.append({"url": ref, "text": ""})
        else:
            # Fallback to old logic if not found in DB
            problem_title, problem_statement, references, error = scrape_codeforces(question_id)
            problem_html = ""
            if references:
                for ref in references:
                    reference_data.append({"url": ref, "text": ""})
        # Fetch system messages based on user preference (stream/subject)
        preferred_streams = []
        try:
            prefs = request.user.preference
            preferred_streams = prefs.streams_and_subjects.all()
        except Exception:
            preferred_streams = []
        if preferred_streams:
            system_messages = SystemMessage.objects.filter(category__in=preferred_streams).order_by('name')
        else:
            # Default to "Coding" stream if exists, else all
            system_messages = SystemMessage.objects.filter(category__name__icontains="coding").order_by('name') or SystemMessage.objects.all().order_by('name')
        # Fetch all LLM models for modal
        llm_models = LLMModel.objects.filter(is_active=True).order_by('name')

        # Construct WebSocket URL
        websocket_scheme = 'wss' if request.is_secure() else 'ws'
        websocket_url = f"{websocket_scheme}://{request.get_host()}/ws/notifications/"
        
        context = {
            "question_id": question_id,
            "problem_title": problem_title,
            "problem_statement": problem_statement,
            "problem_html": problem_html,
            "references": references,
            "reference_data": reference_data,
            "system_messages": system_messages,
            "llm_models": llm_models,
            "error": error,
            "WEBSOCKET_URL": websocket_url,
            "debug_message": "DEBUG: trainer_question_analysis view is being called correctly!",
        }
        print(f"DEBUG: trainer_question_analysis view called for question_id: {question_id}")
        print(f"DEBUG: Using template: trainer_question_analysis.html")
        print(f"DEBUG: WebSocket URL: {websocket_url}")
        return render(request, "trainer_question_analysis.html", context)

@login_required
def trainer_dashboard(request):
    """
    Trainer dashboard: fetches tasks from Google Sheets and displays them.
    """
    user = request.user
    from .models import TrainerTask
    user_full_name = user.get_full_name().strip().lower()
    user_name = user.username.strip().lower()
    user_first_name = user.first_name.strip().lower()
    user_last_name = user.last_name.strip().lower()
    from .models import Project
    projects = Project.objects.filter(is_active=True).order_by('name')
    print("DEBUG: projects count =", projects.count(), "projects =", list(projects.values('id', 'code', 'name', 'is_active')))
    selected_project_id = request.GET.get('project', '').strip()
    # Strict filter: match if developer exactly matches user's full name, username, or first+last name (case-insensitive)
    from django.db.models import Q
    user_full = f"{user_first_name} {user_last_name}".strip()
    # Get all tasks for the selected project, then filter in Python for word-based match
    if selected_project_id:
        all_tasks = TrainerTask.objects.filter(project__id=selected_project_id).order_by('-updated_at')
        # For debugging: get all developer names for this project
        all_developers = list(
            all_tasks.values_list('developer', flat=True).distinct()
        )
        # Word-based match: show if any word in developer matches user's first/last name or username
        user_names = {user_first_name, user_last_name, user_name}
        def is_match(dev):
            if not dev:
                return False
            dev_words = {w.strip().lower() for w in dev.split()}
            return bool(user_names & dev_words)
        filtered_tasks = [task for task in all_tasks if is_match(task.developer)]
    else:
        filtered_tasks = []
        all_developers = []
    # Compute stats by status (using 'completed' field)
    status_counts = {}
    for task in filtered_tasks:
        status = (task.completed or 'Unknown').strip()
        status_counts[status] = status_counts.get(status, 0) + 1

    # Pagination
    page_size = 10
    try:
        page = int(request.GET.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
    total_tasks = len(filtered_tasks)
    total_pages = (total_tasks + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    paginated_tasks = filtered_tasks[start:end]

    # Extract headers from model fields (excluding id, created_at, updated_at)
    headers = [f.name for f in TrainerTask._meta.fields if f.name not in ("id", "created_at", "updated_at")]

    # Compute visible page numbers for pagination (show first, last, current, neighbors, with ellipsis)
    visible_page_numbers = []
    for p in range(1, total_pages + 1):
        if (
            p == 1 or
            p == total_pages or
            (page - 2 <= p <= page + 2)
        ):
            visible_page_numbers.append(p)
        elif p == 2 and page > 4:
            visible_page_numbers.append("...")
        elif p == total_pages - 1 and page < total_pages - 3:
            visible_page_numbers.append("...")

    context = {
        'tasks': paginated_tasks,
        'user': user,
        'stats': status_counts,
        'headers': headers,
        'projects': projects,
        'selected_project': selected_project_id,
        'all_developers': all_developers,  # For debugging
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'previous_page': page - 1 if page > 1 else 1,
            'next_page': page + 1 if page < total_pages else total_pages,
            'total_records': total_tasks,
        },
        'visible_page_numbers': visible_page_numbers,
    }
    return render(request, 'dashboard_trainer.html', context)
    
from .models import TaskSyncConfig, TrainerTask, Project
@login_required
def reviewer_dashboard(request):
    """
    Reviewer dashboard: shows tasks where reviewer matches the logged-in user.
    Supports filtering by project and trainer, and paginates results.
    """
    from django.db.models import Q
    user = request.user
    print(str(user))
    reviewer_names = [
        user.get_full_name().strip().lower(),
        user.username.strip().lower(),
        user.first_name.strip().lower(),
        user.email.strip().lower() if user.email else ""
    ]
    # Filters
    project_id = request.GET.get('project', '').strip()
    trainer_name = request.GET.get('trainer', '').strip()

    print(str(TrainerTask.objects.all()))
    # Filter tasks where reviewer matches the logged-in user's username (case-insensitive)
    base_tasks = TrainerTask.objects.filter(
        reviewer__iexact=user.username
    )
    # Filter by project for stats/trainers/table
    if project_id:
        base_tasks = base_tasks.filter(project__id=project_id)

    # For stats and trainer dropdown: use only project filter (not trainer)
    tasks_for_stats_and_trainers = base_tasks

    # DEBUG: Print the first task's fields for troubleshooting
    first_task = base_tasks.first()
    if first_task:
        print("DEBUG: First reviewer task fields:")
        print("developer:", first_task.developer)
        print("question_id:", first_task.question_id)
        print("problem_link:", first_task.problem_link)
        print("labelling_tool_id_link:", first_task.labelling_tool_id_link)
        print("screenshot_drive_link:", first_task.screenshot_drive_link)
        print("codeforces_submission_id:", first_task.codeforces_submission_id)

    # Get unique trainer names from the filtered queryset (for dropdown)
    trainers_qs = tasks_for_stats_and_trainers.values_list('developer', flat=True).distinct()
    trainers = sorted([t for t in trainers_qs if t and t.strip()])

    # Stats (project filter only)
    total_tasks = tasks_for_stats_and_trainers.count()
    in_progress = tasks_for_stats_and_trainers.filter(completed__iexact='In Progress').count()
    completed = tasks_for_stats_and_trainers.filter(completed__iexact='Completed').count()

    # For table: filter by trainer if provided
    tasks_for_table = tasks_for_stats_and_trainers
    if trainer_name:
        tasks_for_table = tasks_for_table.filter(developer__iexact=trainer_name)

    # Pagination for table
    page_size = 10
    try:
        page = int(request.GET.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
    total_tasks_table = tasks_for_table.count()
    total_pages = (total_tasks_table + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    paginated_tasks = tasks_for_table.order_by('-updated_at')[start:end]

    # For project dropdown
    projects = Project.objects.filter(is_active=True).order_by('name')

    # Compute visible page numbers for pagination (show first, last, current, neighbors, with ellipsis)
    visible_page_numbers = []
    for p in range(1, total_pages + 1):
        if (
            p == 1 or
            p == total_pages or
            (page - 2 <= p <= page + 2)
        ):
            visible_page_numbers.append(p)
        elif p == 2 and page > 4:
            visible_page_numbers.append("...")
        elif p == total_pages - 1 and page < total_pages - 3:
            visible_page_numbers.append("...")

    context = {
        'tasks': paginated_tasks,
        'projects': projects,
        'selected_project': project_id,
        'trainers': trainers,
        'selected_trainer': trainer_name,
        'stats': {
            'total': total_tasks,
            'in_progress': in_progress,
            'completed': completed,
        },
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'previous_page': page - 1 if page > 1 else 1,
            'next_page': page + 1 if page < total_pages else total_pages,
            'total_records': total_tasks_table,
        },
        'visible_page_numbers': visible_page_numbers,
    }
    return render(request, 'dashboard_reviewer.html', context)

@login_required
def task_sync_config_view(request):
    user_role = get_user_role(request.user)
    if user_role != 'admin':
        return redirect('index')
    from .models import TaskSyncHistory, Project
    config = TaskSyncConfig.objects.first()
    message = ""
    # Handle project creation and toggle
    if request.method == "POST" and "create_project" in request.POST:
        code = request.POST.get("project_code", "").strip()
        name = request.POST.get("project_name", "").strip()
        description = request.POST.get("project_description", "").strip()
        if code and name:
            Project.objects.get_or_create(code=code, defaults={"name": name, "description": description, "is_active": True})
            message = "Project created successfully."
    if request.method == "POST" and "toggle_project" in request.POST:
        project_id = request.POST.get("toggle_project")
        project = Project.objects.filter(id=project_id).first()
        if project:
            project.is_active = not project.is_active
            project.save()
            message = f"Project '{project.code}' is now {'active' if project.is_active else 'inactive'}."
    projects = Project.objects.all().order_by('name')
    selected_project_id = None
    if request.method == "POST" and "save_config" in request.POST:
        sheet_url = request.POST.get("sheet_url", "").strip()
        sync_interval = int(request.POST.get("sync_interval_minutes", 60))
        selected_project_id = request.POST.get("project_id", "").strip()
        selected_project = Project.objects.filter(id=selected_project_id).first() if selected_project_id else None
        if config:
            config.sheet_url = sheet_url
            config.sync_interval_minutes = sync_interval
            config.project = selected_project
            config.save()
            message = "Configuration updated successfully."
        else:
            config = TaskSyncConfig.objects.create(
                sheet_url=sheet_url,
                sync_interval_minutes=sync_interval,
                project=selected_project
            )
            message = "Configuration saved successfully."
        # Perform immediate sync after saving config
        from .models import TrainerTask, TaskSyncHistory
        created_count = updated_count = deleted_count = 0
        sync_status = "success"
        sync_summary = ""
        sync_details = ""
        try:
            # Fetch data from the sheet (reuse fetch_trainer_tasks logic, but with the new URL)
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            import os

            # Use the service account json if available
            SERVICE_ACCOUNT_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '../service_account.json'))
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_url(config.sheet_url)
            worksheet = sheet.get_worksheet(0)
            rows = worksheet.get_all_values()
            headers = rows[0]
            data_rows = rows[1:]
            # Build a set of question_ids from the sheet
            sheet_qids = set()
            for row in data_rows:
                row_dict = dict(zip(headers, row))
                qid = row_dict.get("question_id") or row_dict.get("Question Id") or row_dict.get("Question ID")
                if qid:
                    sheet_qids.add(qid)
                    obj, created = TrainerTask.objects.update_or_create(
                        question_id=qid,
                        defaults={**{k.lower().replace(" ", "_"): v for k, v in row_dict.items()}, "project": selected_project}
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
            # Delete tasks not in the sheet for this project
            if selected_project:
                to_delete = TrainerTask.objects.filter(project=selected_project).exclude(question_id__in=sheet_qids)
                deleted_count = to_delete.count()
                to_delete.delete()
            sync_summary = f"{created_count} created, {updated_count} updated, {deleted_count} deleted"
        except Exception as e:
            sync_status = "failure"
            sync_summary = "Sync failed"
            sync_details = str(e)
        # Log sync history
        TaskSyncHistory.objects.create(
            config=config,
            status=sync_status,
            summary=sync_summary,
            details=sync_details,
            created_count=created_count,
            updated_count=updated_count,
            deleted_count=deleted_count,
            sync_type="manual",
            synced_by=request.user.username if request.user.is_authenticated else "system",
        )
        config.last_synced = timezone.now()
        config.save()
        # Redirect to avoid form resubmission on refresh
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect("/task-sync/")
    # Pagination for sync history
    history_qs = TaskSyncHistory.objects.filter(config=config).order_by('-timestamp') if config else []
    page_size = 10
    try:
        page = int(request.GET.get('history_page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
    total_history = history_qs.count() if config else 0
    total_history_pages = (total_history + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    history = history_qs[start:end] if config else []
    history_page_numbers = list(range(1, total_history_pages + 1))

    context = {
        "config": config,
        "message": message,
        "history": history,
        "history_pagination": {
            "current_page": page,
            "total_pages": total_history_pages,
            "has_previous": page > 1,
            "has_next": page < total_history_pages,
            "previous_page": page - 1 if page > 1 else 1,
            "next_page": page + 1 if page < total_history_pages else total_history_pages,
        },
        "history_page_numbers": history_page_numbers,
        "projects": projects,
        "selected_project_id": selected_project_id,
    }
    return render(request, "task_sync_config.html", context)

def index(request):
    from .models import Project
    from django.contrib.auth.models import User
    from django.core.paginator import Paginator
    from django.contrib import messages
    from django.urls import reverse
    from django.contrib.auth import logout

    # Always allow superusers to access the dashboard regardless of email domain
    if request.user.is_superuser or get_user_role(request.user) == 'admin':
        # Handle project active/inactive toggle
        if request.method == "POST" and "toggle_project" in request.POST:
            project_id = request.POST.get("toggle_project")
            project = Project.objects.filter(id=project_id).first()
            if project:
                project.is_active = not project.is_active
                project.save()
                messages.success(request, f"Project '{project.code}' is now {'active' if project.is_active else 'inactive'}.")

        # Pagination for projects
        project_list = Project.objects.all().order_by('name')
        project_page_number = request.GET.get('project_page', 1)
        project_paginator = Paginator(project_list, 10)
        projects_page = project_paginator.get_page(project_page_number)

        # Pagination for users
        user_list = User.objects.all().order_by('username')
        user_page_number = request.GET.get('user_page', 1)
        user_paginator = Paginator(user_list, 10)
        users_page = user_paginator.get_page(user_page_number)

        return render(request, 'dashboard_variant1.html', {
            'projects_page': projects_page,
            'users_page': users_page,
        })

    # If not authenticated, redirect to login
    if not request.user.is_authenticated:
        messages.error(request, 'You must be logged in to access the dashboard.')
        return redirect(reverse('login'))

    # For non-superusers, check if the user's email domain is allowed
    user_email = request.user.email
    allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']

    is_allowed = False
    for domain in allowed_domains:
        if user_email and user_email.endswith('@' + domain):
            is_allowed = True
            break

    # If not allowed, log the user out and redirect to login page with error message
    if not is_allowed:
        messages.error(
            request,
            'Access restricted: Only Official Turing ID is allowed. '
            'You have been logged out for security reasons.'
        )
        logout(request)
        return redirect(reverse('login'))

    # If allowed, continue with normal dashboard rendering
    # Get the user's role
    user_role = get_user_role(request.user)
    # Show different dashboard variants based on user role
    if user_role == 'pod_lead':
        # Pod leads and reviewers: redirect to reviewer dashboard route
        return redirect('reviewer_dashboard')
    else:
        # Trainers: redirect to trainer dashboard route
        return redirect('trainer_dashboard')


@require_http_methods(["POST"])
def bulk_upload(request):
    files = request.FILES.getlist('files')
    if not files:
        messages.error(request, "No files selected for bulk upload.")
        return redirect('convert_jsons')
    
    fs = FileSystemStorage(location='eval/static/uploads/')
    for file in files:
        fs.save(file.name, file)
    
    messages.success(request, f"Successfully uploaded {len(files)} file(s)!")
    return redirect('convert_jsons')

@login_required
@user_passes_test(is_not_trainer)
def convert_jsons(request):
    uploads_fs = FileSystemStorage(location='eval/static/uploads/')
    converted_fs = FileSystemStorage(location='eval/static/converted_jsons/')

    # Get only files, not directories
    uploaded_files = [
        {'name': file, 'url': f'/static/uploads/{file}'}
        for file in uploads_fs.listdir('')[1]
    ]
    
    converted_files = [
        {'name': file, 'url': f'/static/converted_jsons/{file}'}
        for file in converted_fs.listdir('')[1]
    ]

    return render(request, 'convert_jsons.html', {
        'files': uploaded_files,
        'converted_files': converted_files
    })


@require_http_methods(["POST"])
def delete_all_converted_jsons(request):
    fs = FileSystemStorage(location='eval/static/converted_jsons/')
    for file in fs.listdir('')[1]:
        fs.delete(file)
    messages.success(request, "All converted JSON files deleted successfully!")
    return redirect('convert_jsons')

# **Upload File View**
def upload_file(request):
    if request.method == 'POST':
        if 'file' not in request.FILES:
            messages.error(request, 'No file uploaded')
            return redirect('convert_jsons')

        file = request.FILES['file']
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit

        # Validate file size & type
        if file.size > MAX_FILE_SIZE:
            messages.error(request, 'File size cannot exceed 100MB')
            return redirect('convert_jsons')

        if not file.name.lower().endswith(('.py', '.json')):
            messages.error(request, 'Only .py and .json files are allowed')
            return redirect('convert_jsons')

        fs = FileSystemStorage(location='eval/static/uploads/')
        filename = fs.save(file.name, file)
        messages.success(request, f'File {filename} uploaded successfully!')
    
    return redirect('convert_jsons')


# **Delete Single File View**
def delete_file(request, filename):
    if request.method == 'POST':
        fs = FileSystemStorage(location='eval/static/uploads/')
        converted_fs = FileSystemStorage(location='eval/static/converted_jsons/')

        # Check and delete from appropriate directory
        if fs.exists(filename):
            fs.delete(filename)
            messages.success(request, f'File {filename} deleted successfully')
        elif converted_fs.exists(filename):
            converted_fs.delete(filename)
            messages.success(request, f'File {filename} deleted successfully')
        else:
            messages.error(request, f'File {filename} does not exist.')

    return redirect('convert_jsons')


# **Delete All Uploaded Files**
def delete_all_files(request):
    if request.method == 'POST':
        fs = FileSystemStorage(location='eval/static/uploads/')
        for file in fs.listdir('')[1]:  # Only delete files, not directories
            fs.delete(file)
        messages.success(request, 'All files deleted successfully!')
    
    return redirect('convert_jsons')


# **Convert Python Files to JSON**
class CodeToJsonConverter:
    def __init__(self):
        self.section_pattern = re.compile(r'\*\*\[SECTION_(\d+)\]\*\*')
        self.atomic_pattern = re.compile(r'\*\*\[atomic_(\d+)_(\d+)\]\*\*')

    def parse_code_file(self, file_content):
        """Parse the code file content and extract metadata and sections."""
        # Extract metadata
        metadata = self._extract_metadata(file_content)

        # Extract sections and their content
        sections = self._extract_sections(file_content)

        # Create the final JSON structure
        result = {
            "deliverable_id": self._generate_id(),
            "language": {
                "overall": "en_US"  # Default language
            },
            "notes": {
                "notebook_metadata": metadata,
                "annotator_ids": ["cDfeA"],  # Example annotator ID
                "task_category_list": [
                    {
                        "category": metadata.get("Category", ""),
                        "subcategory": metadata.get("Topic", "")
                    }
                ]
            },
            "messages": self._create_messages(file_content, sections)
        }

        return result

    def _extract_metadata(self, content):
        """Extract metadata from the file content."""
        metadata = {}
        metadata_section = re.search(r'# Metadata(.*?)#', content, re.DOTALL)

        if metadata_section:
            metadata_text = metadata_section.group(1)
            for line in metadata_text.split('\n'):
                if ':**' in line:
                    key, value = line.split(':**')
                    metadata[key.strip()] = value.strip()

        return metadata

    def _extract_sections(self, content):
        """Extract all sections and their atomic components."""
        sections = {}
        current_section = None
        current_atomic = None
        lines = content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]
            section_match = self.section_pattern.search(line)
            atomic_match = self.atomic_pattern.search(line)

            if section_match:
                current_section = section_match.group(1)
                sections[current_section] = {
                    "summary": "",
                    "atomics": {}
                }
                i += 1
                continue

            if atomic_match:
                if not current_section:
                    print(f"Warning: Found atomic marker before section marker at line: {line}")
                    i += 1
                    continue

                current_atomic = f"{atomic_match.group(1)}_{atomic_match.group(2)}"
                # Initialize the atomic content
                sections[current_section]["atomics"][current_atomic] = ""

                # Collect all content until the next atomic or section marker
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if self.section_pattern.search(next_line) or self.atomic_pattern.search(next_line):
                        break
                    sections[current_section]["atomics"][current_atomic] += next_line + "\n"
                    i += 1
                continue

            if current_section and line.strip():
                if not any(pattern.search(line) for pattern in [self.section_pattern, self.atomic_pattern]):
                    sections[current_section]["summary"] += line + "\n"

            i += 1

        return sections

    def _create_messages(self, content, sections):
        """Create the messages array for the JSON structure."""
        messages = [
            {
                "role": "user",
                "contents": [
                    {
                        "text": self._extract_prompt(content)
                    }
                ]
            },
            {
                "role": "assistant",
                "contents": [
                    {
                        "text": self._extract_response(content)
                    }
                ],
                "reasoning": {
                    "process": self._create_reasoning_process(sections)
                }
            }
        ]
        return messages

    def _extract_prompt(self, content):
        """Extract the original prompt from the content."""
        prompt_section = re.search(r'\*\*\[PROMPT\]\*\*(.*?)\*\*\[', content, re.DOTALL)
        return prompt_section.group(1).strip() if prompt_section else ""

    def _extract_response(self, content):
        """Extract the response section from the content."""
        response_section = re.search(r'\*\*\[RESPONSE\]\*\*(.*?)$', content, re.DOTALL)
        return response_section.group(1).strip() if response_section else ""

    def _create_reasoning_process(self, sections):
        """Create the reasoning process array from sections."""
        process = []
        # Sort sections by their numeric ID to maintain order
        for section_id in sorted(sections.keys(), key=int):
            section_data = sections[section_id]
            section_entry = {
                "summary": section_data["summary"].strip(),
                "thoughts": []
            }

            # Sort atomics by their IDs to maintain order
            for atomic_id in sorted(section_data["atomics"].keys()):
                atomic_content = section_data["atomics"][atomic_id]
                if atomic_content.strip():  # Only add non-empty thoughts
                    section_entry["thoughts"].append({
                        "text": atomic_content.strip()
                    })

            if section_entry["thoughts"]:  # Only add sections with thoughts
                process.append(section_entry)

        return process

    def _generate_id(self):
        """Generate a unique identifier."""
        return f"code-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
def convert_to_json(request):
    if request.method == 'POST':
        selected_files = request.POST.getlist('selected_files')
        source_fs = FileSystemStorage(location='eval/static/uploads/')
        target_fs = FileSystemStorage(location='eval/static/converted_jsons/')
        
        for py_file in selected_files:
            if py_file.endswith('.py'):
                try:
                    with source_fs.open(py_file, 'r') as file:
                        py_content = file.read()

                    converter = CodeToJsonConverter()
                    result = converter.parse_code_file(py_content)

                    json_filename = py_file.replace('.py', '.json')
                    with target_fs.open(json_filename, 'w') as json_file:
                        json.dump(result, json_file, indent=4)

                    messages.success(request, f'Successfully converted {py_file} to JSON')
                except Exception as e:
                    messages.error(request, f'Error converting {py_file}: {str(e)}')

    return redirect('convert_jsons')


# **Validation Check**
@ensure_csrf_cookie
@login_required
@user_passes_test(is_not_trainer)
def validation_check(request):
    converted_fs = FileSystemStorage(location='eval/static/converted_jsons/')
    
    converted_files = [
        {'name': file, 'url': f'/static/converted_jsons/{file}'}
        for file in converted_fs.listdir('')[1] if file.endswith('.json')
    ]
    
    validations = Validation.objects.all()
    
    return render(request, 'validation_check.html', {
        'converted_files': converted_files,
        'validations': validations
    })


@require_http_methods(["POST"])
def perform_validation(request):
    try:
        data = json.loads(request.body)
        file_names = data.get('files', [])
        validation_ids = data.get('validations', [])
        
        fs = FileSystemStorage(location='eval/static/converted_jsons/')
        results = []

        for file_name in file_names:
            file_path = fs.path(file_name)
            
            if not os.path.isfile(file_path):
                results.append({
                    'file': file_name,
                    'validations': [{
                        'name': 'File Check',
                        'status': 'error',
                        'message': 'File not found'
                    }]
                })
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
            except json.JSONDecodeError as e:
                results.append({
                    'file': file_name,
                    'validations': [{
                        'name': 'JSON Parse',
                        'status': 'error',
                        'message': f'Invalid JSON: {str(e)}'
                    }]
                })
                continue

            file_results = []
            for validation_id in validation_ids:
                validation = Validation.objects.filter(validation_id=validation_id).first()
                
                if not validation:
                    file_results.append({
                        'name': f'Validation {validation_id}',
                        'status': 'error',
                        'message': 'Validation not found'
                    })
                    continue

                try:
                    validation_code = validation.validation.strip()

                    # 🔹 Remove any surrounding triple quotes
                    validation_code = validation_code.strip('"""').strip("'''").strip()

                    # 🔹 Ensure that function follows correct format
                    if not validation_code.startswith("def "):
                        file_results.append({
                            'name': validation.name,
                            'status': 'error',
                            'message': 'Invalid function format in DB'
                        })
                        continue

                    # 🔹 Extract function name using regex
                    match = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", validation_code)
                    if not match:
                        file_results.append({
                            'name': validation.name,
                            'status': 'error',
                            'message': 'Could not detect function name'
                        })
                        continue
                    
                    function_name = match.group(1)
                    # print(f"Detected function name: {function_name}")  # Debug log

                    # 🔹 Prepare execution scope
                    local_scope = {"json": json}

                    # print(f"Available in local_scope: {local_scope.keys()}") # Debug log

                    # 🔹 Execute function definition safely
                    exec(validation_code, {}, local_scope)

                    # 🔹 Retrieve function
                    func = local_scope.get(function_name)
                    if not callable(func):
                        file_results.append({
                            'name': validation.name,
                            'status': 'error',
                            'message': f'No valid function found in stored code'
                        })
                        continue

                    # 🔹 Execute function with JSON data
                    result = func(json_data)
                    # print(f"Function executed successfully, result: {result}")  # Debug log

                    # 🔹 Validate result format
                    if isinstance(result, tuple) and len(result) == 2:
                        success, message = result
                        file_results.append({
                            'name': validation.name,
                            'status': 'success' if success else 'error',
                            'message': str(message)
                        })
                    else:
                        file_results.append({
                            'name': validation.name,
                            'status': 'error',
                            'message': 'Invalid validation result format'
                        })
                
                except Exception as e:
                    file_results.append({
                        'name': validation.name,
                        'status': 'error',
                        'message': f'Validation execution error: {str(e)}'
                    })
            
            results.append({
                'file': file_name,
                'validations': file_results
            })

        return JsonResponse({'results': results}, safe=False)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON request body'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)
   
# **Logical Consistency Check**
@login_required
@user_passes_test(is_not_trainer)
def logical_checks(request):
    fs = FileSystemStorage(location='eval/static/converted_jsons/')
    json_files = [file for file in fs.listdir('')[1] if file.endswith('.json')]
    print("___________________")
    print(f"JSON files: {json_files}")
    print("___________________")
    
    return render(request, 'logical_checks.html', {'json_files': json_files})


@require_POST
def perform_logical_analysis(request):
    selected_files = request.POST.getlist('json_files')
    if not selected_files:
        return JsonResponse({"error": "No JSON files selected for logical analysis."}, status=400)
    
    base_path = os.path.join(settings.BASE_DIR, 'eval/static/converted_jsons/')
    filepaths = [os.path.join(base_path, name) for name in selected_files]
    
    # OpenAI API key is already stored in your .env and accessed via settings
    api_key = settings.OPENAI_API_KEY

    analysis_results = analyze_reasoning_for_files(filepaths, api_key)

    # Save analysis data to the Coherence Model
    try:
        coherence_record = Coherence.objects.create(
            text=json.dumps(filepaths),
            response=json.dumps(analysis_results),
            username=request.user
        )
    except Exception as e:
        return JsonResponse({"error": f"Error saving analysis results: {str(e)}"}, status=500)
        
    return JsonResponse({"analysis_results": analysis_results})

@login_required
def model_evaluation(request):
    llm_models = LLMModel.objects.all().order_by('name')
    user = request.user
    try:
        prefs = user.preference
        preferred_streams = prefs.streams_and_subjects.all()
        system_messages = SystemMessage.objects.filter(category__in=preferred_streams).order_by('name')
    except UserPreference.DoesNotExist:
        system_messages = SystemMessage.objects.none()
        preferred_streams = StreamAndSubject.objects.none()
    return render(request, 'model_eval.html', {
        'llm_models': llm_models,
        'default_system_messages': system_messages,
        'streams_and_subjects': StreamAndSubject.objects.all().order_by('name'),
        'preferred_streams': preferred_streams,
    })

def evaluate_model_async(model_id, manual_prompt, system_message, session_id, username):
    """Evaluate a single model asynchronously"""
    try:
        print(f"Starting evaluation for model ID: {model_id} in session: {session_id}")
        model = LLMModel.objects.get(id=model_id)
        if not model.is_active:
            print(f"Model {model.name} is inactive, skipping")
            result = {
                'model_name': model.name,
                'status': 'error',
                'response': 'This model is currently inactive',
                'timing': 0,
                'time_taken': 0
            }
            model_results_queues[session_id].put(result)
            print(f"Added inactive result for {model.name} to queue")
            return result

        start_time = time.time()
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": manual_prompt})

        try:
            from .utils.ai_client import get_ai_client
            # Fetch API key from model or DB, not from environment
            api_key = model.api_key or "FETCH_FROM_DB(f'{model.provider.upper()}_API_KEY')"
            client = get_ai_client(model.provider, api_key, model.name)

            result = client.get_response(messages, temperature=model.temperature)
            elapsed_time = round(time.time() - start_time, 2)

            if result['status'] == 'success':
                result = {
                    'model_name': model.name,
                    'status': 'success',
                    'response': result['response'],
                    'timing': elapsed_time,
                    'time_taken': elapsed_time
                }
            else:
                result = {
                    'model_name': model.name,
                    'status': 'error',
                    'response': result['error'],
                    'timing': 0,
                    'time_taken': 0
                }
            
            # Automatically save successful evaluations to history
            try:
                ModelEvaluationHistory.objects.create(
                    model_name=model.name,
                    prompt=manual_prompt,
                    system_instructions=system_message,
                    temperature=model.temperature if model.temperature is not None else 0.7,
                    max_tokens=2048,  # Default value
                    evaluation_metrics={'timing': elapsed_time, 'status': 'success'},
                    response=response_text,
                    username=username
                )
                print(f"Automatically saved evaluation for {model.name} to history")
            except Exception as save_error:
                print(f"Error saving to history: {str(save_error)}")
                
        except Exception as e:
            print(f"API Error for {model.name}: {str(e)}")
            result = {
                'model_name': model.name,
                'status': 'error',
                'response': f'API Error: {str(e)}',
                'timing': 0,
                'time_taken': 0
            }

    except LLMModel.DoesNotExist:
        print(f"Model with ID {model_id} not found")
        result = {
            'model_name': f'Unknown Model (ID: {model_id})',
            'status': 'error',
            'response': 'Model not found',
            'timing': 0,
            'time_taken': 0
        }
    
    # Add result to the queue
    model_results_queues[session_id].put(result)
    print(f"Added result for {result['model_name']} to queue, status: {result['status']}")
    
    # Return the result
    return result

@require_http_methods(["POST"])
def evaluate_models(request):
    try:
        data = json.loads(request.body)
        models = data.get('models', [])
        manual_prompt = data.get('manual_prompt', '')
        system_message = data.get('system_message', '')
        
        if not models:
            return JsonResponse({'error': 'No models selected'}, status=400)
        
        if not manual_prompt:
            return JsonResponse({'error': 'Prompt is required'}, status=400)
        
        # Generate a unique session ID for this evaluation
        session_id = str(uuid.uuid4())
        
        # Create a queue for this session
        model_results_queues[session_id] = queue.Queue()
        
        # Initialize the results array for this session
        model_results[session_id] = []
        
        # Store selected models in the session for later use
        request.session['selected_models'] = models
        
        # Store the current session ID in the session
        request.session['current_session_id'] = session_id
        
        def run_single_evaluation(model_id, prompt, system_msg, sess_id):
            try:
                result = evaluate_model_async(model_id, prompt, system_msg, sess_id, request.user)
                return result
            except Exception as e:
                return {'error': str(e), 'model_id': model_id}
        
        # Start evaluation threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as executor:
            futures = [
                executor.submit(run_single_evaluation, model_id, manual_prompt, system_message, session_id)
                for model_id in models
            ]
        
        return JsonResponse({'session_id': session_id})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def get_model_results(request, session_id):
    """Get the results of model evaluation for a specific session."""
    try:
        # Only log once per 10 requests or on important events
        should_log = random.random() < 0.1  # Log roughly 10% of requests
        
        if should_log:
            print(f"Getting results for session: {session_id}")
        
        # Initialize the results array for this session if it doesn't exist
        if session_id not in model_results:
            model_results[session_id] = []
            print(f"Initialized empty results array for session: {session_id}")
        
        # Get the last seen index from the query parameters
        last_seen_index = int(request.GET.get('last_seen', '0'))
        
        # Check if there are any new results in the queue
        new_result = None
        try:
            # Get only one result at a time from the queue to ensure immediate display
            if session_id in model_results_queues and not model_results_queues[session_id].empty():
                new_result = model_results_queues[session_id].get_nowait()
                
                # Make sure evaluation_metrics is present in the result
                if 'evaluation_metrics' not in new_result and hasattr(new_result, 'get'):
                    new_result['evaluation_metrics'] = new_result.get('metrics', {})
                
                model_results[session_id].append(new_result)
                print(f"Added new result for model: {new_result['model_name']}")
                print(f"Result data: {new_result}")
                
                # Return the new result immediately
                current_index = len(model_results[session_id])
                completed = len(model_results[session_id])
                total = request.session.get('selected_models', [])
                total_models = len(total)
                
                print(f"Returning 1 new result (total completed: {completed}, queue size: {model_results_queues[session_id].qsize() if session_id in model_results_queues else 0})")
                
                # Find active threads for this session to determine which models are still processing
                processing_models = []
                active_threads = [t for t in threading.enumerate() if t.name.startswith(f"eval-{session_id}")]
                
                if not active_threads and completed < total_models:
                    # If no active threads but not all models completed, some may have failed silently
                    print(f"Warning: No active threads but only {completed}/{total_models} completed")
                
                return JsonResponse({
                    'results': [new_result],
                    'completed': completed,
                    'total': total_models,
                    'processing': processing_models,
                    'current_index': current_index,
                    'has_more': True  # Always check for more results
                })
        except queue.Empty:
            # Queue is empty, continue to check for previously processed results
            pass
        except Exception as e:
            print(f"Error getting results from queue: {str(e)}")
            # We'll try returning previously processed results instead
        
        # If there's no new result from the queue, check if there are any results
        # that the client hasn't seen yet (based on last_seen_index)
        if last_seen_index < len(model_results[session_id]):
            # Return just the next unseen result
            next_result = model_results[session_id][last_seen_index]
            
            # Make sure evaluation_metrics is present in the result
            if 'evaluation_metrics' not in next_result and hasattr(next_result, 'get'):
                next_result['evaluation_metrics'] = next_result.get('metrics', {})
            
            current_index = last_seen_index + 1
            
            completed = len(model_results[session_id])
            total = request.session.get('selected_models', [])
            total_models = len(total)
            
            if should_log:
                print(f"Returning 1 previously processed result (total completed: {completed})")
                print(f"Result data: {next_result}")
            
            return JsonResponse({
                'results': [next_result],
                'completed': completed,
                'total': total_models,
                'processing': [],
                'current_index': current_index,
                'has_more': current_index < len(model_results[session_id]) or (session_id in model_results_queues and not model_results_queues[session_id].empty())
            })
        
        # If there are no new results, return an empty list
        completed = len(model_results[session_id])
        total = request.session.get('selected_models', [])
        total_models = len(total)
        
        # Check if there are any active threads for this session
        active_threads = [t for t in threading.enumerate() if t.name.startswith(f"eval-{session_id}")]
        has_more = len(active_threads) > 0 or (session_id in model_results_queues and not model_results_queues[session_id].empty())
        
        if should_log and (has_more or completed < total_models):
            print(f"No new results to return (total completed: {completed}, active threads: {len(active_threads)})")
        
        # Return a special response code for the "no results yet" case
        return JsonResponse({
            'results': [],
            'completed': completed,
            'total': total_models,
            'processing': [],
            'current_index': last_seen_index,
            'has_more': has_more
        }, status=204 if not has_more and completed == 0 else 200)  # Use 204 for "No Content Yet"
        
    except Exception as e:
        print(f"Error in get_model_results: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    

@login_required
@user_passes_test(is_not_trainer)
def reports(request):
    # Get page number from query parameters, default to 1
    page = request.GET.get('page', 1)
    try:
        page = int(page)
        if page < 1:
            page = 1
    except ValueError:
        page = 1
    
    # Set pagination parameters
    items_per_page = 100
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    
    # Get the analytics reports from the database, filtered by user
    all_reports = AnalysisResult.objects.filter(user=request.user).order_by('-timestamp')
    
    # Get unique models for filter dropdown
    unique_models = AnalysisResult.objects.filter(user=request.user).values_list('model__name', flat=True).distinct()
    
    # Calculate total pages
    total_reports = all_reports.count()
    total_pages = (total_reports + items_per_page - 1) // items_per_page  # Ceiling division
    
    # Get the reports for the current page
    reports = all_reports[start_index:end_index]
    
    # Prepare pagination context
    pagination = {
        'current_page': page,
        'total_pages': total_pages,
        'has_previous': page > 1,
        'has_next': page < total_pages,
        'previous_page': page - 1 if page > 1 else 1,
        'next_page': page + 1 if page < total_pages else total_pages,
        'total_records': total_reports
    }

    return render(request, 'reports.html', {
        'reports': reports,
        'pagination': pagination,
        'unique_models': unique_models
    })

# API endpoint to get all reports data for export
@login_required
@user_passes_test(is_not_trainer)
def api_all_reports(request):
    # Get all reports for the current user
    all_reports = AnalysisResult.objects.filter(user=request.user).order_by('-timestamp')
    
    # Convert to a list of dictionaries
    reports_data = []
    for report in all_reports:
        reports_data.append({
            'id': report.id,
            'file_name': report.file_name,
            'model': report.model.name if report.model else 'Unknown',
            'prompt': report.prompt.name if report.prompt else 'No prompt available',
            'analysis': report.analysis,
            'timestamp': report.timestamp.isoformat()
        })
    
    return JsonResponse({'reports': reports_data})

@require_http_methods(["POST"])
def save_to_history(request):
    """Save a model evaluation to history."""
    try:
        data = json.loads(request.body)
        
        # Create a new history entry
        history_entry = ModelEvaluationHistory.objects.create(
            model_name=data.get('model_name', 'Unknown Model'),
            prompt=data.get('prompt', ''),
            system_instructions=data.get('system_instructions', ''),
            temperature=data.get('temperature', 0.7),
            max_tokens=data.get('max_tokens', 2048),
            evaluation_metrics=data.get('evaluation_metrics', {}),
            response=data.get('response', ''),
            username=request.user
        )
        
        return JsonResponse({
            'success': True,
            'id': str(history_entry.evaluation_id)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@require_http_methods(["GET"])
def get_evaluation_history(request):
    """Get the latest evaluation history for the current user, or a specific item by ID."""
    try:
        # Check if a specific ID is requested
        item_id = request.GET.get('id')
        
        if item_id:
            # Get a specific history item
            history = ModelEvaluationHistory.objects.filter(
                evaluation_id=item_id,
                username=request.user,
                is_active=True
            )
        else:
            # Get the last 10 history items
            history = ModelEvaluationHistory.objects.filter(
                username=request.user,
                is_active=True
            ).order_by('-created_at')[:10]
        
        history_data = []
        for item in history:
            history_data.append({
                'id': str(item.evaluation_id),
                'model_name': item.model_name,
                'prompt': item.prompt,
                'system_instructions': item.system_instructions,
                'temperature': item.temperature,
                'max_tokens': item.max_tokens,
                'evaluation_metrics': item.evaluation_metrics,
                'response': item.response,
                'formatted_response': item.formatted_response,
                'is_edited': item.is_edited,
                'edit_history': item.edit_history,
                'created_at': item.created_at.isoformat()
            })
        
        return JsonResponse({
            'success': True,
            'history': history_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def get_model_analytics(request):
    """Get model evaluation analytics data for the admin dashboard."""
    try:
        # Get the last 30 days of evaluations
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_evaluations = ModelEvaluationHistory.objects.filter(
            created_at__gte=thirty_days_ago,
            is_active=True
        )

        # Calculate overall metrics
        total_evaluations = recent_evaluations.count()
        successful_evaluations = recent_evaluations.filter(
            evaluation_metrics__has_key='status',
            evaluation_metrics__status='success'
        ).count()

        # Calculate accuracy (based on successful evaluations)
        accuracy = (successful_evaluations / total_evaluations * 100) if total_evaluations > 0 else 0

        # Calculate average response time
        response_times = [
            eval.evaluation_metrics.get('timing', 0) 
            for eval in recent_evaluations 
            if 'timing' in eval.evaluation_metrics
        ]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Calculate error rate
        error_rate = ((total_evaluations - successful_evaluations) / total_evaluations * 100) if total_evaluations > 0 else 0

        # Calculate throughput (evaluations per day)
        throughput = total_evaluations / 30  # per day

        # Get model-wise performance
        model_performance = {}
        for eval in recent_evaluations:
            if eval.model_name not in model_performance:
                model_performance[eval.model_name] = {
                    'total': 0,
                    'successful': 0,
                    'total_time': 0
                }
            
            model_performance[eval.model_name]['total'] += 1
            if eval.evaluation_metrics.get('status') == 'success':
                model_performance[eval.model_name]['successful'] += 1
            model_performance[eval.model_name]['total_time'] += eval.evaluation_metrics.get('timing', 0)

        # Calculate per-model metrics
        model_metrics = []
        for model_name, stats in model_performance.items():
            model_accuracy = (stats['successful'] / stats['total'] * 100) if stats['total'] > 0 else 0
            avg_time = stats['total_time'] / stats['total'] if stats['total'] > 0 else 0
            model_error_rate = ((stats['total'] - stats['successful']) / stats['total'] * 100) if stats['total'] > 0 else 0

            model_metrics.append({
                'model_name': model_name,
                'accuracy': round(model_accuracy, 1),
                'response_time': round(avg_time, 2),
                'error_rate': round(model_error_rate, 1),
                'total_evaluations': stats['total']
            })

        # Get daily trends for the last 30 days
        daily_trends = []
        for i in range(30):
            date = timezone.now() - timezone.timedelta(days=i)
            day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timezone.timedelta(days=1)
            
            day_evaluations = recent_evaluations.filter(created_at__range=(day_start, day_end))
            day_successful = day_evaluations.filter(
                evaluation_metrics__has_key='status',
                evaluation_metrics__status='success'
            ).count()
            
            daily_trends.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'total': day_evaluations.count(),
                'successful': day_successful,
                'accuracy': (day_successful / day_evaluations.count() * 100) if day_evaluations.count() > 0 else 0
            })

        return JsonResponse({
            'success': True,
            'metrics': {
                'accuracy': round(accuracy, 1),
                'response_time': round(avg_response_time, 2),
                'error_rate': round(error_rate, 1),
                'throughput': round(throughput, 1),
                'total_evaluations': total_evaluations
            },
            'model_metrics': model_metrics,
            'daily_trends': daily_trends
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def get_user_analytics(request):
    """Get user analytics data for the dashboard."""
    try:
        print("get_user_analytics called by user:", request.user.username)
        
        # Get the last 30 days of evaluations
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_evaluations = ModelEvaluationHistory.objects.filter(
            created_at__gte=thirty_days_ago,
            is_active=True
        )
        
        print(f"Found {recent_evaluations.count()} evaluations in the last 30 days")

        # Get unique users and their evaluation counts
        user_stats = {}
        for eval in recent_evaluations:
            username = eval.username.username
            if username not in user_stats:
                user_stats[username] = {
                    'total_evaluations': 0,
                    'successful_evaluations': 0,
                    'total_response_time': 0,
                    'models_used': set()
                }
            
            user_stats[username]['total_evaluations'] += 1
            if eval.evaluation_metrics.get('status') == 'success':
                user_stats[username]['successful_evaluations'] += 1
            user_stats[username]['total_response_time'] += eval.evaluation_metrics.get('timing', 0)
            user_stats[username]['models_used'].add(eval.model_name)

        print(f"Found {len(user_stats)} unique users with evaluations")

        # Calculate per-user metrics
        user_metrics = []
        for username, stats in user_stats.items():
            success_rate = (stats['successful_evaluations'] / stats['total_evaluations'] * 100) if stats['total_evaluations'] > 0 else 0
            avg_response_time = stats['total_response_time'] / stats['total_evaluations'] if stats['total_evaluations'] > 0 else 0

            user_metrics.append({
                'username': username,
                'total_evaluations': stats['total_evaluations'],
                'success_rate': round(success_rate, 1),
                'avg_response_time': round(avg_response_time, 2),
                'models_used': len(stats['models_used'])
            })

        # Sort users by total evaluations
        user_metrics.sort(key=lambda x: x['total_evaluations'], reverse=True)
        
        print(f"Returning {len(user_metrics)} user metrics")
        print("Sample user metrics:", user_metrics[:2] if user_metrics else "No user metrics")

        return JsonResponse({
            'success': True,
            'user_metrics': user_metrics
        })
    except Exception as e:
        print(f"Error in get_user_analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@require_POST
def save_edited_response(request):
    """Save an edited model response."""
    try:
        data = json.loads(request.body)
        response_id = data.get('response_id')
        model_id = data.get('model_id')
        edited_content = data.get('edited_content')
        
        print(f"Saving edited response: response_id={response_id}, model_id={model_id}")
        
        if not edited_content:
            return JsonResponse({'success': False, 'error': 'Missing edited content'})
        
        # Get the current session ID from the request
        session_id = request.session.get('current_session_id')
        
        # If no session ID in the session, try to get it from the model_results keys
        if not session_id and model_results:
            # Use the most recent session ID (assuming it's the current one)
            session_id = list(model_results.keys())[-1]
            print(f"Using most recent session ID: {session_id}")
            # Store it in the session for future use
            request.session['current_session_id'] = session_id
        
        # Debug information
        print(f"Available sessions: {list(model_results.keys())}")
        
        # First, try to find and update the record in the database
        db_updated = False
        
        try:
            # Try to find by model_id first (most common case)
            if model_id:
                # Look for recent evaluations with this model
                history_entries = ModelEvaluationHistory.objects.filter(
                    model_name=model_id,
                    username=request.user
                ).order_by('-created_at')[:5]  # Get the most recent ones
                
                if history_entries.exists():
                    # Update the most recent one
                    entry = history_entries.first()
                    # Use save_edit method to properly track edit history
                    if hasattr(entry, 'save_edit') and callable(getattr(entry, 'save_edit')):
                        entry.save_edit(edited_content, request.user)
                    else:
                        entry.response = edited_content
                        entry.formatted_response = edited_content
                        entry.is_edited = True
                        entry.save()
                    print(f"Updated database entry for model {model_id}")
                    db_updated = True
            
            # If we couldn't find by model_id, try by response_id if it's a UUID
            if not db_updated and response_id:
                try:
                    # Check if response_id is a valid UUID
                    import uuid
                    uuid_obj = uuid.UUID(response_id)
                    entry = ModelEvaluationHistory.objects.filter(evaluation_id=uuid_obj).first()
                    if entry:
                        # Use save_edit method to properly track edit history
                        if hasattr(entry, 'save_edit') and callable(getattr(entry, 'save_edit')):
                            entry.save_edit(edited_content, request.user)
                        else:
                            entry.response = edited_content
                            entry.formatted_response = edited_content
                            entry.is_edited = True
                            entry.save()
                        print(f"Updated database entry with ID {response_id}")
                        db_updated = True
                except (ValueError, TypeError):
                    # Not a valid UUID, continue with in-memory updates
                    pass
        except Exception as db_error:
            print(f"Error updating database: {str(db_error)}")
            # Continue with in-memory updates even if DB update fails
        
        # Now update the in-memory model_results as well
        memory_updated = False
        
        # Try to find the result by response_id directly
        if response_id and response_id in model_results:
            print(f"Found result by response_id: {response_id}")
            model_results[response_id]['response'] = edited_content
            memory_updated = True
        
        # Try to find the result in the session by model_id
        if not memory_updated and session_id and session_id in model_results:
            print(f"Checking session {session_id} with {len(model_results[session_id])} results")
            
            # Check if model_results[session_id] is a list or a dict
            if isinstance(model_results[session_id], list):
                for i, result in enumerate(model_results[session_id]):
                    print(f"Comparing model_id: {result.get('model_id')} with {model_id}")
                    if str(result.get('model_id')) == str(model_id) or result.get('model_name') == model_id:
                        print(f"Found match at index {i}")
                        model_results[session_id][i]['response'] = edited_content
                        memory_updated = True
                        break
            elif isinstance(model_results[session_id], dict):
                # If it's a dict, update directly
                if str(model_results[session_id].get('model_id')) == str(model_id) or model_results[session_id].get('model_name') == model_id:
                    model_results[session_id]['response'] = edited_content
                    memory_updated = True
        
        # If we still haven't found it, try searching all sessions
        if not memory_updated:
            for sess_id, results in model_results.items():
                print(f"Searching session {sess_id}")
                if isinstance(results, list):
                    for i, result in enumerate(results):
                        if str(result.get('model_id')) == str(model_id) or result.get('model_name') == model_id:
                            print(f"Found match in session {sess_id} at index {i}")
                            model_results[sess_id][i]['response'] = edited_content
                            memory_updated = True
                            break
                    if memory_updated:
                        break
                elif isinstance(results, dict):
                    if str(results.get('model_id')) == str(model_id) or results.get('model_name') == model_id:
                        model_results[sess_id]['response'] = edited_content
                        memory_updated = True
                        break
        
        # Last resort: create a new entry in the current session and database
        if not memory_updated and not db_updated and session_id:
            print(f"Creating new entry in session {session_id}")
            new_result = {
                'model_id': model_id,
                'model_name': 'Edited Response',
                'response': edited_content,
                'status': 'success'
            }
            
            if isinstance(model_results.get(session_id, []), list):
                model_results[session_id].append(new_result)
            else:
                model_results[session_id] = [new_result]
            
            # Also create a new database entry
            try:
                # Get the prompt from the form if available
                prompt_text = request.POST.get('manual_prompt', '')
                if not prompt_text:
                    # Try to get it from an existing result
                    for sess_id, results in model_results.items():
                        if isinstance(results, list) and results:
                            # Use the first result's prompt if available
                            break
                
                # Create new history entry
                new_entry = ModelEvaluationHistory.objects.create(
                    model_name=model_id or 'Edited Response',
                    prompt=prompt_text or 'Unknown prompt',
                    response=edited_content,
                    formatted_response=edited_content,
                    is_edited=True,
                    username=request.user
                )
                
                # Initialize edit history if needed
                if hasattr(new_entry, 'edit_history'):
                    new_entry.edit_history = [{
                        'previous_content': '',
                        'edited_at': timezone.now().isoformat(),
                        'editor': request.user.username
                    }]
                    new_entry.save()
                print(f"Created new database entry for edited response")
                db_updated = True
            except Exception as create_error:
                print(f"Error creating new database entry: {str(create_error)}")
            
            memory_updated = True
        
        if memory_updated or db_updated:
            return JsonResponse({
                'success': True,
                'db_updated': db_updated,
                'memory_updated': memory_updated
            })
        
        # If we reach here, we couldn't find the result to update
        print(f"Could not find response to update. response_id={response_id}, model_id={model_id}")
        return JsonResponse({
            'success': False, 
            'error': 'Could not find the response to update. Please try again.'
        })
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Invalid JSON in request'})
    except Exception as e:
        print(f"Error saving edited response: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@require_POST
@login_required
def save_user_preferences(request):
    try:
        data = request.POST
        selected_ids = request.POST.getlist('streams')
        user = request.user
        prefs, created = UserPreference.objects.get_or_create(user=user)
        prefs.streams_and_subjects.set(selected_ids)
        prefs.save()
        return JsonResponse({'success': True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@ensure_csrf_cookie
def ground_truth(request):
    """
    View for the ground truth validation page.
    This page is available to all user profiles.
    """
    # Get the user's role if authenticated
    user_role = get_user_role(request.user) if request.user.is_authenticated else None
    
    # You can customize what data is shown based on user role if needed
    context = {
        'user_role': user_role,
        # Add any other context data needed for the ground truth page
    }
    
    return render(request, 'ground_truth.html', context)

from django.views.decorators.http import require_GET

from django.contrib.auth.decorators import login_required

@login_required
def edit_trainer_task(request, task_id):
    """
    Edit a TrainerTask: GET shows form, POST saves changes.
    """
    from .models import TrainerTask
    from django.core.validators import URLValidator
    from django.core.exceptions import ValidationError

    task = TrainerTask.objects.filter(id=task_id).first()
    if not task:
        messages.error(request, "Task not found.")
        return redirect('trainer_dashboard')

    # Scrape/render prompt if needed
    question_prompt = task.raw_prompt or ""
    if not question_prompt and task.problem_link:
        # Try to scrape the problem statement from the problem_link
        try:
            import requests
            from bs4 import BeautifulSoup
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36"
            }
            resp = requests.get(task.problem_link, headers=headers, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                statement_tag = soup.find("div", class_="problem-statement")
                if statement_tag:
                    question_prompt = statement_tag.text.strip()
        except Exception as e:
            question_prompt = f"Could not fetch prompt: {str(e)}"

    if request.method == "POST":
        # Get form data
        problem_link = request.POST.get("problem_link", "").strip()
        codeforces_submission_id = request.POST.get("codeforces_submission_id", "").strip()
        completed = request.POST.get("completed", "").strip()

        # Validation
        errors = []
        # Validate Google Colab Link (problem_link)
        url_validator = URLValidator()
        try:
            url_validator(problem_link)
        except ValidationError:
            errors.append("Please enter a valid Google Colab URL.")
        # Submission Id required
        if not codeforces_submission_id:
            errors.append("Submission Id is required.")
        # Status required
        if not completed:
            errors.append("Status is required.")

        if errors:
            return render(request, "edit_trainer_task.html", {
                "task": task,
                "question_prompt": question_prompt,
                "errors": errors,
                "form": {
                    "problem_link": problem_link,
                    "codeforces_submission_id": codeforces_submission_id,
                    "completed": completed,
                }
            })

        # Save changes
        task.problem_link = problem_link
        task.codeforces_submission_id = codeforces_submission_id
        task.completed = completed
        task.save()
        messages.success(request, "Task updated successfully.")
        return redirect('trainer_dashboard')

    # GET: Render form
    return render(request, "edit_trainer_task.html", {
        "task": task,
        "question_prompt": question_prompt,
        "errors": [],
        "form": {
            "problem_link": task.problem_link or "",
            "codeforces_submission_id": task.codeforces_submission_id or "",
            "completed": task.completed or "",
        }
    })

@login_required
def review_question(request, question_id):
    """
    Reviewer: Review a question by question_id.
    Renders the review page with input for Google Colab link, model selection, and review UI.
    """
    return render(request, "review.html", {"question_id": question_id})

@require_GET
def get_llm_models(request):
    models = LLMModel.objects.filter(is_active=True).order_by('name')
    data = [
        {"id": model.id, "name": model.name, "description": model.description or ""}
        for model in models
    ]
    return JsonResponse({"models": data})
# These functions are already defined above, so we don't need duplicates

from django.contrib.auth.decorators import login_required

@login_required
def modal_playground(request):
    """
    Renders the LLM Modal Playground page.
    Allows filtering system messages by selected stream/subject.
    """
    from .models import StreamAndSubject, SystemMessage, LLMModel

    # Get all streams/subjects for dropdowns
    streams_and_subjects = StreamAndSubject.objects.all().order_by('name')

    # Get selected stream/subject from GET params
    selected_stream_id = request.GET.get('stream')
    selected_subject_id = request.GET.get('subject')  # If you want to support both

    # Filter system messages by selected stream/subject
    system_messages = SystemMessage.objects.all().order_by('name')
    if selected_stream_id:
        system_messages = system_messages.filter(category_id=selected_stream_id)
    elif selected_subject_id:
        system_messages = system_messages.filter(category_id=selected_subject_id)

    # Get all active LLM models
    llm_models = LLMModel.objects.filter(is_active=True).order_by('name')

    context = {
        "streams_and_subjects": streams_and_subjects,
        "selected_stream_id": selected_stream_id,
        "selected_subject_id": selected_subject_id,
        "system_messages": system_messages,
        "llm_models": llm_models,  # Only active models are passed
    }
    return render(request, "modal_playground.html", context)
