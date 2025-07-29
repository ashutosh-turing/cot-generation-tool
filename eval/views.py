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
from .utils import logger

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
                messages.error(request, "Access denied: You do not have permission to access this page.")
                return redirect('index')
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
def trainer_question_analysis(request, project_id, question_id):
    """
    View for trainer to analyze a specific question, project-aware and config-driven.
    - GET: Uses config to fetch and map fields, falls back to scraping if needed.
    - POST: Runs analysis and returns chain of thought as JSON.
    """
    import json as pyjson
    from django.utils.html import escape
    from django.http import JsonResponse
    from .models import TaskSyncConfig, TrainerTask, Project

    # Helper to scrape content from URL
    def scrape_content(url):
        problem_title = ""
        problem_statement = ""
        references = []
        error = None
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
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

    # Helper to scrape Codeforces
    def scrape_codeforces(qid):
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

    # Fetch config for this project
    config = TaskSyncConfig.objects.filter(project__id=project_id, is_active=True).first()
    mapping = config.column_mapping if config else {}
    primary_key = config.primary_key_column if config else "question_id"
    scraping_needed = config.scraping_needed if config else False
    link_column = config.link_column if config else None

    if request.method == "POST":
        # Handle AJAX analysis request for LLM analysis
        system_message = request.POST.get("system_message", "")
        additional_context = request.POST.get("additional_context", "")
        llm_model_ids = request.POST.getlist("llm_models")
        # Compose the prompt
        prompt = request.POST.get("prompt", "")
        # If prompt is not provided, use mapped field from TrainerTask
        filter_kwargs = {primary_key: question_id, "project__id": project_id}
        task = TrainerTask.objects.filter(**filter_kwargs).first()
        if not prompt and task:
            prompt_field = mapping.get("prompt", "raw_prompt")
            prompt = getattr(task, prompt_field, "") or getattr(task, "raw_prompt", "")
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
                    "project_id": str(project_id),
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
        filter_kwargs = {primary_key: question_id, "project__id": project_id}
        task = TrainerTask.objects.filter(**filter_kwargs).first()
        reference_data = []
        extra_fields = {}
        problem_title = ""
        problem_statement = ""
        problem_html = ""
        error = None
        references = []
        if task:
            # Map fields using config
            problem_title = getattr(task, mapping.get("title", "title"), "") or ""
            prompt_field = mapping.get("prompt", "raw_prompt")
            problem_statement = getattr(task, prompt_field, "") or getattr(task, "raw_prompt", "")
            problem_html = ""  # Could be extended for HTML if needed
            # Reference links
            ref_field = mapping.get("reference_links", "response_links")
            ref_val = getattr(task, ref_field, "")
            if ref_val:
                import ast
                try:
                    links = ast.literal_eval(ref_val)
                    if isinstance(links, list):
                        references = [str(link).strip().strip("'").strip('"') for link in links if str(link).strip()]
                    else:
                        references = [str(links).strip()]
                except Exception:
                    references = [link.strip().strip("'").strip('"') for link in ref_val.split(",") if link.strip()]
            # Scraping fallback if needed
            if scraping_needed and link_column and getattr(task, link_column, None):
                link = getattr(task, link_column)
                problem_title, problem_statement, references, error = scrape_content(link)

            # Collect all mapped extra fields
            for logical, sheet_col in mapping.items():
                if logical not in ("prompt", "title", "reference_links"):
                    extra_fields[logical] = getattr(task, sheet_col, "")
            # Always define reference_data
            if references:
                for ref in references:
                    reference_data.append({"url": ref, "text": ""})
        else:
            # Fallback to scraping if config allows, else show error
            if scraping_needed:
                problem_title, problem_statement, references, error = scrape_codeforces(question_id)
                problem_html = ""
                if references:
                    for ref in references:
                        reference_data.append({"url": ref, "text": ""})
            else:
                error = "Task not found for this project and question ID."
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
        # Fetch project-tied LLM models for this project
        from .models import ProjectLLMModel
        project_llm_models = ProjectLLMModel.objects.filter(project_id=project_id, is_active=True).select_related('llm_model')
        if project_llm_models.exists():
            llm_models = project_llm_models.filter(is_active=True).order_by('llm_model__name')
        else:
            llm_models = LLMModel.objects.filter(is_active=True, is_default=True).order_by('name')
            if not llm_models.exists():
                llm_models = LLMModel.objects.filter(is_active=True).order_by('name')

        # Construct WebSocket URL
        websocket_scheme = 'wss' if request.is_secure() else 'ws'
        websocket_url = f"{websocket_scheme}://{request.get_host()}/ws/notifications/"
        
        context = {
            "question_id": question_id,
            "project_id": project_id,
            "problem_title": problem_title,
            "problem_statement": problem_statement,
            "problem_html": problem_html,
            "references": references,
            "reference_data": reference_data,
            "extra_fields": extra_fields,
            "system_messages": system_messages,
            "llm_models": llm_models,
            "error": error,
            "WEBSOCKET_URL": websocket_url,
            "debug_message": "DEBUG: trainer_question_analysis view is being called correctly!",
        }
        logger.log(f"DEBUG: trainer_question_analysis view called for project_id: {project_id}, question_id: {question_id}")
        logger.log(f"DEBUG: Using template: trainer_question_analysis.html")
        logger.log(f"DEBUG: WebSocket URL: {websocket_url}")
        return render(request, "trainer_question_analysis.html", context)

@login_required
def trainer_dashboard(request):
    """
    Trainer dashboard: fetches tasks from Google Sheets and displays them with productivity insights.
    """
   
    from .models import TrainerTask, UserActivitySession, UserProductivityInsight, LLMJob
    from datetime import datetime, timedelta
    from django.utils import timezone
    from .models import Project
    projects = Project.objects.filter(is_active=True).order_by('name')
    logger.log("DEBUG: projects count =", projects.count(), "projects =", list(projects.values('id', 'code', 'name', 'is_active')))
    selected_project_id = request.GET.get('project', '').strip()
    selected_trainer = request.GET.get('trainer', '').strip()
    user_role = get_user_role(request.user)
    is_admin = user_role == 'admin'

    # Get all trainers from the User table (trainer group)
    from django.contrib.auth.models import Group
    try:
        trainer_group = Group.objects.get(name='trainer')
        trainers_qs = User.objects.filter(groups=trainer_group)
        # Exclude admins and staff
        trainers_qs = trainers_qs.exclude(is_superuser=True).exclude(is_staff=True)
        all_trainers = sorted([t.username for t in trainers_qs if t.username and t.username.strip()])
        logger.log(f"DEBUG: Found {len(all_trainers)} users in trainer group: {all_trainers}")
    except Group.DoesNotExist:
        all_trainers = []
        logger.log("DEBUG: 'trainer' group does not exist.")
    
    # Priority-based exact match: try username first, then fall back to others
    def is_exact_match(dev, user=None):
        if user is None:
            user = request.user
        if not dev or not user:
            return False
        dev_clean = str(dev).strip().lower()
        user_name = user.username.strip().lower()
        user_email = user.email.strip().lower()
        user_full_name = user.get_full_name().strip().lower()
        user_first_name = user.first_name.strip().lower()
        user_last_name = user.last_name.strip().lower()
        if dev_clean == user_name:
            return True
        if dev_clean in user_email:
            return True
        if dev_clean in user_full_name:
            return True
        if dev_clean == user_first_name:
            return True
        if dev_clean == user_last_name:
            return True
        return False
 

    # Get all tasks for the selected project, then filter for exact developer match
    if selected_project_id:
        all_tasks = TrainerTask.objects.filter(project__id=selected_project_id).order_by('-updated_at')

        if is_admin and selected_trainer:
            # Admin: filter by selected trainer if provided (try user match, fallback to substring)
            selected_user = User.objects.filter(username=selected_trainer).first()
            if selected_user:
                filtered_tasks = [task for task in all_tasks if task.developer and is_exact_match(task.developer, selected_user)]
            else:
                filtered_tasks = [task for task in all_tasks if task.developer and selected_trainer.strip().lower() in str(task.developer).strip().lower()]
        else:
            filtered_tasks = [task for task in all_tasks if is_exact_match(task.developer)]

        logger.log(f"DEBUG: Found {len(filtered_tasks)} tasks after admin/user filtering")
        if filtered_tasks:
            sample_developers = [task.developer for task in filtered_tasks[:3]]
            logger.log(f"DEBUG: Sample matching developers: {sample_developers}")
    else:
        filtered_tasks = []
        all_trainers = []
    
    # Calculate privacy-first productivity statistics
    week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get this week's activity sessions for the user
    this_week_sessions = UserActivitySession.objects.filter(
        user=user,
        session_start__date__range=[week_start, week_end],
        session_end__isnull=False
    )
    
    # Get LLM job statistics for the user (this week)
    this_week_llm_jobs = LLMJob.objects.filter(
        user=user,
        created_at__date__range=[week_start, week_end]
    )
    
    # Calculate trainer-focused statistics
    total_focus_time = sum(session.focus_time_minutes for session in this_week_sessions)
    total_sessions = this_week_sessions.count()
    analysis_sessions = this_week_sessions.filter(activity_type='trainer_analysis').count()
    modal_sessions = this_week_sessions.filter(activity_type='modal_playground').count()
    llm_experiments = this_week_llm_jobs.count()
    
    # Calculate average session length
    avg_session_length = total_focus_time / max(total_sessions, 1)
    
    # Format focus time in hours and minutes
    focus_hours = total_focus_time // 60
    focus_minutes = total_focus_time % 60
    focus_time_display = f"{focus_hours}h {focus_minutes}m" if focus_hours > 0 else f"{focus_minutes}m"
    
    # Create productivity statistics for display
    productivity_stats = {
        'focus_time_this_week': focus_time_display,
        'focus_time_minutes': total_focus_time,
        'deep_analysis_sessions': analysis_sessions,
        'llm_experiments': llm_experiments,
        'learning_velocity': len([task for task in filtered_tasks if task.completed and task.completed.lower() in ['completed', 'done']]),
        'avg_session_length': f"{int(avg_session_length)}m" if avg_session_length > 0 else "0m",
        'modal_playground_usage': modal_sessions,
        'total_sessions': total_sessions
    }
    
    # Compute traditional task stats by status (using 'completed' field) - keep for compatibility
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

    # Dynamic headers based on TaskSyncConfig
    config = None
    headers = []
    field_types = {}
    field_labels = {}
    
    if selected_project_id:
        config = TaskSyncConfig.objects.filter(project__id=selected_project_id, is_active=True).first()
        if config:
            # Use the config's display fields method
            headers = config.get_display_fields()
            logger.log(f"headers => {headers}")
            # Get field types and labels
            for field in headers:
                field_types[field] = config.get_field_type(field)
                field_labels[field] = config.get_field_label(field)
        else:
            # Fallback to default fields
            headers = ["question_id", "problem_link", "response_links", "completed"]
            for field in headers:
                field_types[field] = 'text'
                field_labels[field] = field.replace('_', ' ').title()
    else:
        # Default headers when no project selected
        headers = ["question_id", "problem_link", "response_links", "completed"]
        for field in headers:
            field_types[field] = 'text'
            field_labels[field] = field.replace('_', ' ').title()

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
        'productivity_stats': productivity_stats,  # New productivity insights
        'headers': headers,
        'field_types': field_types,
        'field_labels': field_labels,
        'projects': projects,
        'selected_project': selected_project_id,
        'all_trainers': all_trainers,
        'selected_trainer': selected_trainer,
        'has_admin_role': is_admin,
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'previous_page': page - 1 if page > 1 else 1,
            'next_page': page + 1 if page < total_tasks else total_pages,
            'total_records': total_tasks,
        },
        'visible_page_numbers': visible_page_numbers,
    }
    return render(request, 'dashboard_trainer.html', context)
    
from .models import TaskSyncConfig, TrainerTask, Project
@login_required
def reviewer_dashboard(request):
    """
    Reviewer dashboard: shows tasks where reviewer matches the logged-in user with productivity insights.
    Supports filtering by project and trainer, and paginates results.
    """
    from django.db.models import Q
    from django.db import transaction
    from .models import UserActivitySession, LLMJob
    from datetime import datetime, timedelta
    from django.utils import timezone
    import time
    
    user = request.user
    logger.log(f"DEBUG: Current user: {user.username}, Full name: {user.get_full_name()}, Email: {user.email}")
    
    # Filters
    project_id = request.GET.get('reviewer_project', '').strip()
    trainer_name = request.GET.get('reviewer_trainer', '').strip()

    # Add retry logic for database operations
    max_retries = 3
    retry_delay = 0.1  # 100ms
    
    for attempt in range(max_retries):
        try:
            logger.log(f"Database query attempt {attempt + 1}")
            
            # Filter tasks based on user role
            user_role = get_user_role(user)
            logger.log(f"DEBUG: User {user.username} determined as role: {user_role}")
            
            with transaction.atomic():
                if user_role == 'admin':
                    # Only admins can see all tasks
                    base_tasks = TrainerTask.objects.all()
                    logger.log(f"DEBUG: User {user.username} is {user_role}, showing all tasks")
                else:
                    # Pod leads and regular reviewers only see tasks assigned to them
                    # Get all tasks first, then filter using priority-based exact matching
                    all_reviewer_tasks = TrainerTask.objects.filter(
                        Q(reviewer__isnull=False) & Q(reviewer__gt='')
                    ).distinct()
                    
                    # Get user identifiers for matching
                    user_full_name = user.get_full_name().strip().lower()
                    user_name = user.username.strip().lower()
                    user_email = user.email.strip().lower()     
                    user_first_name = user.first_name.strip().lower()
                    user_last_name = user.last_name.strip().lower()
                    
                    # Get all reviewer names for debugging
                    all_reviewers = list(all_reviewer_tasks.values_list('reviewer', flat=True).distinct())
                    
                    # Debug: Print user information and available reviewers
                    logger.log(f"DEBUG: Current reviewer user - username: '{user_name}', first_name: '{user_first_name}', last_name: '{user_last_name}', full_name: '{user_full_name}'")
                    logger.log(f"DEBUG: Available reviewers in database: {all_reviewers}")
                    
                    # Priority-based exact match: try username first, then fall back to others
                    def is_reviewer_match(reviewer):
                        if not reviewer:
                            return False
                        reviewer_clean = reviewer.strip().lower()
                        
                        # Priority 1: Try username first (most specific)
                        if reviewer_clean == user_name:
                            return True
                        
                        if reviewer_clean in user_email:
                            return True
                        # Priority 2: Try full name if username doesn't match
                        if reviewer_clean in user_full_name:
                            return True
                        
                        # Priority 3: Try first name if neither username nor full name match
                        if reviewer_clean == user_first_name:
                            return True
                        
                        # Priority 4: Try last name as final fallback
                        if reviewer_clean == user_last_name:
                            return True
                        
                        # No match found
                        return False
                    
                    # Filter tasks using priority-based matching
                    matching_tasks = [task for task in all_reviewer_tasks if is_reviewer_match(task.reviewer)]
                    
                    # Convert back to QuerySet for consistency with rest of the code
                    if matching_tasks:
                        task_ids = [task.id for task in matching_tasks]
                        base_tasks = TrainerTask.objects.filter(id__in=task_ids)
                    else:
                        base_tasks = TrainerTask.objects.none()
                    
                    logger.log(f"DEBUG: User {user.username} is {user_role}, filtering by assignment")
                    
                    # Debug: Print filtering results
                    task_count = base_tasks.count()
                    logger.log(f"DEBUG: Found {task_count} tasks matching current reviewer out of {all_reviewer_tasks.count()} total reviewer tasks")
                    if matching_tasks:
                        sample_reviewers = [task.reviewer for task in matching_tasks[:3]]
                        logger.log(f"DEBUG: Sample matching reviewers: {sample_reviewers}")
                    
                    # If no tasks found, show available reviewers for debugging
                    if task_count == 0:
                        logger.log(f"DEBUG: No tasks found for reviewer matching: {user.username}, {user.get_full_name()}, {user.first_name}, {user.last_name}")
                
                # Force evaluation of the queryset to catch database errors early
                task_count = base_tasks.count()
                logger.log(f"DEBUG: Total tasks after filtering: {task_count}")
            break
            
        except Exception as e:
            logger.log(f"Database error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                # If all retries failed, return an error page
                messages.error(request, f"Database error: {str(e)}. Please try again later.")
                return render(request, 'dashboard_reviewer.html', {
                    'tasks': [],
                    'projects': [],
                    'selected_project': '',
                    'trainers': [],
                    'selected_trainer': '',
                    'stats': {'total': 0, 'in_progress': 0, 'completed': 0},
                    'productivity_stats': {},
                    'pagination': {
                        'current_page': 1,
                        'total_pages': 0,
                        'has_previous': False,
                        'has_next': False,
                        'previous_page': 1,
                        'next_page': 1,
                        'total_records': 0,
                    },
                    'visible_page_numbers': [],
                    'database_error': True,
                })
    # Filter by project for stats/trainers/table
    if project_id:
        base_tasks = base_tasks.filter(project__id=project_id)

    # For stats and trainer dropdown: use only project filter (not trainer)
    tasks_for_stats_and_trainers = base_tasks

    # DEBUG: Print the first task's fields for troubleshooting
    first_task = base_tasks.first()
    if first_task:
        logger.log("DEBUG: First reviewer task fields:")
        logger.log("developer:", first_task.developer)
        logger.log("question_id:", first_task.question_id)
        logger.log("problem_link:", first_task.problem_link)
        logger.log("labelling_tool_id_link:", first_task.labelling_tool_id_link)
        logger.log("screenshot_drive_link:", first_task.screenshot_drive_link)
        logger.log("codeforces_submission_id:", first_task.codeforces_submission_id)

    # Get all users from the 'trainer' group for the dropdown, excluding the logged-in user
    from django.contrib.auth.models import Group
    try:
        trainer_group = Group.objects.get(name='trainer')
        admin_group = Group.objects.filter(name='admin').first()
        # Exclude logged-in user, superusers, staff, and admin group members
        trainers_qs = User.objects.filter(groups=trainer_group)
        if admin_group:
            trainers_qs = trainers_qs.exclude(groups=admin_group)
        trainers_qs = trainers_qs.exclude(id=user.id).exclude(is_superuser=True).exclude(is_staff=True)
        trainers = sorted([t for t in trainers_qs.values_list('username', flat=True) if t and t.strip()])
        logger.log(f"DEBUG: Found {len(trainers)} users in trainer group (excluding logged-in user and admins): {trainers}")
    except Group.DoesNotExist:
        logger.log("DEBUG: 'trainer' group does not exist, falling back to developer field")
        # Fallback to existing logic if trainer group doesn't exist, excluding the logged-in user and admins
        admin_usernames = set(User.objects.filter(
            is_superuser=True
        ).values_list('username', flat=True)) | set(User.objects.filter(
            is_staff=True
        ).values_list('username', flat=True)) | set(User.objects.filter(
            groups__name='admin'
        ).values_list('username', flat=True))
        trainers_qs = tasks_for_stats_and_trainers.values_list('developer', flat=True).distinct()
        trainers = sorted([
            t for t in trainers_qs
            if t and t.strip() and t != user.username and t not in admin_usernames
        ])

    # Calculate privacy-first productivity statistics for reviewers
    week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get this week's activity sessions for the user
    this_week_sessions = UserActivitySession.objects.filter(
        user=user,
        session_start__date__range=[week_start, week_end],
        session_end__isnull=False
    )
    
    # Get LLM job statistics for the user (this week)
    this_week_llm_jobs = LLMJob.objects.filter(
        user=user,
        created_at__date__range=[week_start, week_end]
    )
    
    # Calculate reviewer-focused statistics
    total_focus_time = sum(session.focus_time_minutes for session in this_week_sessions)
    total_sessions = this_week_sessions.count()
    review_sessions = this_week_sessions.filter(activity_type='review_task').count()
    analysis_sessions = this_week_sessions.filter(activity_type='trainer_analysis').count()
    llm_experiments = this_week_llm_jobs.count()
    
    # Calculate average review time
    avg_review_time = total_focus_time / max(review_sessions, 1) if review_sessions > 0 else 0
    
    # Format focus time in hours and minutes
    focus_hours = total_focus_time // 60
    focus_minutes = total_focus_time % 60
    focus_time_display = f"{focus_hours}h {focus_minutes}m" if focus_hours > 0 else f"{focus_minutes}m"
    
    # Create reviewer productivity statistics for display
    reviewer_productivity_stats = {
        'review_focus_time': focus_time_display,
        'focus_time_minutes': total_focus_time,
        'review_sessions': review_sessions,
        'quality_assurance_time': f"{int(avg_review_time)}m" if avg_review_time > 0 else "0m",
        'tasks_reviewed': len([task for task in tasks_for_stats_and_trainers if task.completed and task.completed.lower() in ['completed', 'done']]),
        'analysis_sessions': analysis_sessions,
        'llm_experiments': llm_experiments,
        'total_sessions': total_sessions
    }

    # Traditional stats (project filter only)
    total_tasks = tasks_for_stats_and_trainers.count()
    in_progress = tasks_for_stats_and_trainers.filter(completed__iexact='In Progress').count()
    completed = tasks_for_stats_and_trainers.filter(completed__iexact='Completed').count()

    # For table: filter by trainer if provided
    tasks_for_table = tasks_for_stats_and_trainers
    if trainer_name:
        tasks_for_table = tasks_for_table.filter(developer__iexact=trainer_name)

    # Admin-only: Filter by reviewer if provided
    reviewer_name = ""
    reviewer_list = []
    user_role = get_user_role(user)
    if user_role == "admin":
        reviewer_name = request.GET.get("reviewer_reviewer", "").strip()
        # Get all unique reviewers for dropdown
        reviewer_list = list(
            tasks_for_stats_and_trainers.values_list("reviewer", flat=True)
            .exclude(reviewer__isnull=True)
            .exclude(reviewer__exact="")
            .distinct()
        )
        reviewer_list = sorted([r for r in reviewer_list if r and r.strip()])
        if reviewer_name:
            tasks_for_table = tasks_for_table.filter(reviewer__iexact=reviewer_name)

    # Dynamic headers based on TaskSyncConfig.column_mapping if available
    config = None
    config_headers = []
    if project_id:
        config = TaskSyncConfig.objects.filter(project__id=project_id, is_active=True).first()
        if config and config.column_mapping:
            # For reviewer dashboard, exclude developer/reviewer fields since users only see their own tasks
            # Use the display_config field_order if available, otherwise use column_mapping keys
            if config.display_config and 'field_order' in config.display_config:
                config_headers = [field for field in config.display_config['field_order'] 
                                if field not in ['developer', 'reviewer']]
            else:
                # Add logical fields from column_mapping (excluding developer/reviewer fields)
                config_headers = ["question_id"]  # Always include question_id first
                for logical_field in config.column_mapping.keys():
                    if logical_field not in config_headers and logical_field not in ['developer', 'reviewer']:
                        config_headers.append(logical_field)
        else:
            # Fallback to model fields if no config (excluding developer/reviewer)
            config_headers = ["question_id", "problem_link"]
    else:
        config_headers = ["question_id", "problem_link"]
    headers = config_headers

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

    # Use the same flexible system as trainer dashboard
    field_types = {}
    field_labels = {}
    
    if config:
        # Get field types and labels from config
        for field in headers:
            field_types[field] = config.get_field_type(field)
            field_labels[field] = config.get_field_label(field)
    else:
        # Default field types and labels
        for field in headers:
            field_types[field] = 'text'
            field_labels[field] = field.replace('_', ' ').title()

    context = {
        'tasks': paginated_tasks,  # Use the actual task objects, not processed data
        'headers': headers,
        'field_types': field_types,
        'field_labels': field_labels,
        'projects': projects,
        'selected_project': project_id,
        'trainers': trainers,
        'selected_trainer': trainer_name,
        # 'selected_status': selected_status,  # Removed status filter
        'reviewer_list': reviewer_list,
        'selected_reviewer': reviewer_name,
        'user_role': user_role,
        'stats': {
            'total': total_tasks,
            'in_progress': in_progress,
            'completed': completed,
        },
        'productivity_stats': reviewer_productivity_stats,  # New reviewer productivity insights
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
@role_required(['admin'])
def task_sync_config_view(request):
    from .models import TaskSyncHistory, Project
    config = TaskSyncConfig.objects.first()
    message = ""

    # Handle config.json upload
    if request.method == "POST" and "upload_config_json" in request.POST and request.FILES.get("config_json"):
        try:
            import json
            config_file = request.FILES["config_json"]
            config_data = json.load(config_file)

            # Accept either project_code or project_id
            project_code = config_data.get("project_code")
            project_id = config_data.get("project_id")
            project = None
            if project_id:
                project = Project.objects.filter(id=project_id).first()
            elif project_code:
                project = Project.objects.filter(code=project_code).first()
            if not project:
                message = "Project not found for the given project_code or project_id."
            else:
                # Map config fields
                sheet_url = config_data.get("sheet_url", "").strip()
                sync_interval = int(config_data.get("sync_interval_minutes", 60))
                primary_key_column = config_data.get("primary_key_column", "question_id")
                scraping_needed = bool(config_data.get("scraping_needed", False))
                link_column = config_data.get("link_column", "")
                column_mapping = config_data.get("column_mapping", {})
                field_types = config_data.get("field_types", {})
                display_config = config_data.get("display_config", {})
                sync_mode = config_data.get("sync_mode", "prompt_in_sheet")
                sheet_tab = config_data.get("sheet_tab", "")
                is_active = config_data.get("is_active", True)

                # Validate required fields
                if not sheet_url:
                    message = "sheet_url is required in config.json."
                else:
                    # Find or create config for this project
                    config = TaskSyncConfig.objects.filter(project=project).first()
                    if config:
                        config.sheet_url = sheet_url
                        config.sync_interval_minutes = sync_interval
                        config.project = project
                        config.primary_key_column = primary_key_column
                        config.scraping_needed = scraping_needed
                        config.link_column = link_column
                        config.column_mapping = column_mapping
                        config.field_types = field_types
                        config.display_config = display_config
                        config.sync_mode = sync_mode
                        config.sheet_tab = sheet_tab
                        config.is_active = is_active
                        config.save()
                        message = "Configuration updated from config.json."
                    else:
                        config = TaskSyncConfig.objects.create(
                            sheet_url=sheet_url,
                            sync_interval_minutes=sync_interval,
                            project=project,
                            primary_key_column=primary_key_column,
                            scraping_needed=scraping_needed,
                            link_column=link_column,
                            column_mapping=column_mapping,
                            field_types=field_types,
                            display_config=display_config,
                            sync_mode=sync_mode,
                            sheet_tab=sheet_tab,
                            is_active=is_active
                        )
                        message = "Configuration created from config.json."
                    # --- Trigger sync after config upload ---
                    try:
                        from .utils.sheets import sync_trainer_tasks
                        sync_status, sync_summary, sync_details, created_count, updated_count, deleted_count = sync_trainer_tasks(
                            config, selected_project=project, sync_type="manual", synced_by=request.user.username if request.user.is_authenticated else "system"
                        )
                        message += f" Sync: {sync_summary}"
                    except Exception as sync_exc:
                        message += f" Sync failed: {str(sync_exc)}"
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.log(tb)
            message = f"Failed to process config.json: {str(e)}\nTraceback:\n{tb}"

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

        # New config fields
        primary_key_column = request.POST.get("primary_key_column", "").strip() or "question_id"
        scraping_needed = request.POST.get("scraping_needed", "") == "on"
        link_column = request.POST.get("link_column", "").strip()
        column_mapping_raw = request.POST.get("column_mapping", "").strip()
        try:
            column_mapping = json.loads(column_mapping_raw) if column_mapping_raw else {}
        except Exception:
            column_mapping = {}
        sync_mode = request.POST.get("sync_mode", "prompt_in_sheet")
        sheet_tab = request.POST.get("sheet_tab", "").strip()

        if config:
            config.sheet_url = sheet_url
            config.sync_interval_minutes = sync_interval
            config.project = selected_project
            config.primary_key_column = primary_key_column
            config.scraping_needed = scraping_needed
            config.link_column = link_column
            config.column_mapping = column_mapping
            config.sync_mode = sync_mode
            config.sheet_tab = sheet_tab
            config.save()
            message = "Configuration updated successfully."
        else:
            config = TaskSyncConfig.objects.create(
                sheet_url=sheet_url,
                sync_interval_minutes=sync_interval,
                project=selected_project,
                primary_key_column=primary_key_column,
                scraping_needed=scraping_needed,
                link_column=link_column,
                column_mapping=column_mapping,
                sync_mode=sync_mode,
                sheet_tab=sheet_tab
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
            import traceback
            tb = traceback.format_exc()
            logger.log(tb)
            sync_status = "failure"
            sync_summary = "Sync failed"
            sync_details = f"{str(e)}\nTraceback:\n{tb}"
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
    
    # Get project filter parameter
    selected_project_filter = request.GET.get('project_filter', '')
    
    # Get sync configurations - show all or filter by project
    sync_configs = TaskSyncConfig.objects.all().order_by('-created_at')
    if selected_project_filter and selected_project_filter != 'all':
        try:
            filter_project = Project.objects.get(id=selected_project_filter)
            sync_configs = sync_configs.filter(project=filter_project)
            config = sync_configs.first()
        except Project.DoesNotExist:
            pass  # Invalid project ID, show all results
    
    # Pagination for sync history with project filtering
    if config:
        history_qs = TaskSyncHistory.objects.filter(config=config).order_by('-timestamp')
    else:
        # If no specific config, get all history and allow filtering by project
        history_qs = TaskSyncHistory.objects.all().order_by('-timestamp')
    
    # Apply project filter if selected
    if selected_project_filter and selected_project_filter != 'all':
        try:
            filter_project = Project.objects.get(id=selected_project_filter)
            history_qs = history_qs.filter(config__project=filter_project)
        except Project.DoesNotExist:
            pass  # Invalid project ID, show all results
    
    page_size = 10
    try:
        page = int(request.GET.get('history_page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
    total_history = history_qs.count()
    total_history_pages = (total_history + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    history = history_qs[start:end]
    history_page_numbers = list(range(1, total_history_pages + 1))

    context = {
        "config": config,
        "message": message,
        "history": history,
        "sync_configs": sync_configs,  # Add sync configurations to context
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
        "selected_project_filter": selected_project_filter,
    }
    return render(request, "task_sync_config.html", context)

def index(request):
    from .models import Project, TrainerTask, UserActivitySession, LLMJob
    from django.contrib.auth.models import User
    from django.core.paginator import Paginator
    from django.contrib import messages
    from django.urls import reverse
    from django.contrib.auth import logout
    from django.db.models import Count, Q
    from datetime import datetime, timedelta
    from django.utils import timezone

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

        # Calculate comprehensive admin statistics
        week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
        week_end = week_start + timedelta(days=6)
        
        # Overall system statistics
        total_projects = Project.objects.count()
        active_projects = Project.objects.filter(is_active=True).count()
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        total_tasks = TrainerTask.objects.count()
        completed_tasks = TrainerTask.objects.filter(completed__iexact='Completed').count()
        
        # This week's activity
        this_week_sessions = UserActivitySession.objects.filter(
            session_start__date__range=[week_start, week_end],
            session_end__isnull=False
        )
        this_week_llm_jobs = LLMJob.objects.filter(
            created_at__date__range=[week_start, week_end]
        )
        
        # Calculate productivity metrics
        total_focus_time = sum(session.focus_time_minutes for session in this_week_sessions)
        total_sessions = this_week_sessions.count()
        unique_active_users = this_week_sessions.values('user').distinct().count()
        
        # Format focus time
        focus_hours = total_focus_time // 60
        focus_minutes = total_focus_time % 60
        focus_time_display = f"{focus_hours}h {focus_minutes}m" if focus_hours > 0 else f"{focus_minutes}m"
        
        # Per-project statistics
        project_stats = []
        for project in Project.objects.all().order_by('name'):
            project_tasks = TrainerTask.objects.filter(project=project)
            project_completed = project_tasks.filter(completed__iexact='Completed').count()
            project_in_progress = project_tasks.filter(completed__iexact='In Progress').count()
            project_pending = project_tasks.exclude(
                Q(completed__iexact='Completed') | Q(completed__iexact='In Progress')
            ).count()
            
            # Get unique trainers and reviewers for this project
            trainers = project_tasks.values('developer').distinct().count()
            reviewers = project_tasks.values('reviewer').distinct().count()
            
            project_stats.append({
                'project': project,
                'total_tasks': project_tasks.count(),
                'completed': project_completed,
                'in_progress': project_in_progress,
                'pending': project_pending,
                'completion_rate': (project_completed / project_tasks.count() * 100) if project_tasks.count() > 0 else 0,
                'trainers': trainers,
                'reviewers': reviewers
            })
        
        # User role statistics
        admin_users = User.objects.filter(Q(is_superuser=True) | Q(groups__name='admin')).distinct().count()
        pod_lead_users = User.objects.filter(groups__name='pod_lead').count()
        trainer_users = User.objects.filter(groups__name='trainer').count()
        
        # LLM job statistics
        llm_job_stats = {
            'total': this_week_llm_jobs.count(),
            'completed': this_week_llm_jobs.filter(status='completed').count(),
            'failed': this_week_llm_jobs.filter(status='failed').count(),
            'pending': this_week_llm_jobs.filter(status='pending').count(),
            'processing': this_week_llm_jobs.filter(status='processing').count(),
        }
        
        # Create admin statistics
        admin_stats = {
            'total_projects': total_projects,
            'active_projects': active_projects,
            'total_users': total_users,
            'active_users': active_users,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'completion_rate': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            'focus_time_this_week': focus_time_display,
            'total_sessions': total_sessions,
            'unique_active_users': unique_active_users,
            'admin_users': admin_users,
            'pod_lead_users': pod_lead_users,
            'trainer_users': trainer_users,
            'llm_jobs': llm_job_stats
        }

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
            'admin_stats': admin_stats,
            'project_stats': project_stats,
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
                    logger.log(f"Warning: Found atomic marker before section marker at line: {line}")
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
                    # logger.log(f"Detected function name: {function_name}")  # Debug log

                    # 🔹 Prepare execution scope
                    local_scope = {"json": json}

                    # logger.log(f"Available in local_scope: {local_scope.keys()}") # Debug log

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
                    # logger.log(f"Function executed successfully, result: {result}")  # Debug log

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
    logger.log("___________________")
    logger.log(f"JSON files: {json_files}")
    logger.log("___________________")
    
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
        logger.log(f"Starting evaluation for model ID: {model_id} in session: {session_id}")
        model = LLMModel.objects.get(id=model_id)
        if not model.is_active:
            logger.log(f"Model {model.name} is inactive, skipping")
            result = {
                'model_name': model.name,
                'status': 'error',
                'response': 'This model is currently inactive',
                'timing': 0,
                'time_taken': 0
            }
            model_results_queues[session_id].put(result)
            logger.log(f"Added inactive result for {model.name} to queue")
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
            client = get_ai_client(model.provider, api_key, model.name, model)

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
                    response=result['response'],
                    username=username
                )
                logger.log(f"Automatically saved evaluation for {model.name} to history")
            except Exception as save_error:
                logger.log(f"Error saving to history: {str(save_error)}")
                
        except Exception as e:
            logger.log(f"API Error for {model.name}: {str(e)}")
            result = {
                'model_name': model.name,
                'status': 'error',
                'response': f'API Error: {str(e)}',
                'timing': 0,
                'time_taken': 0
            }

    except LLMModel.DoesNotExist:
        logger.log(f"Model with ID {model_id} not found")
        result = {
            'model_name': f'Unknown Model (ID: {model_id})',
            'status': 'error',
            'response': 'Model not found',
            'timing': 0,
            'time_taken': 0
        }
    
    # Add result to the queue
    model_results_queues[session_id].put(result)
    logger.log(f"Added result for {result['model_name']} to queue, status: {result['status']}")
    
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
            logger.log(f"Getting results for session: {session_id}")
        
        # Initialize the results array for this session if it doesn't exist
        if session_id not in model_results:
            model_results[session_id] = []
            logger.log(f"Initialized empty results array for session: {session_id}")
        
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
                logger.log(f"Added new result for model: {new_result['model_name']}")
                logger.log(f"Result data: {new_result}")
                
                # Return the new result immediately
                current_index = len(model_results[session_id])
                completed = len(model_results[session_id])
                total = request.session.get('selected_models', [])
                total_models = len(total)
                
                logger.log(f"Returning 1 new result (total completed: {completed}, queue size: {model_results_queues[session_id].qsize() if session_id in model_results_queues else 0})")
                
                # Find active threads for this session to determine which models are still processing
                processing_models = []
                active_threads = [t for t in threading.enumerate() if t.name.startswith(f"eval-{session_id}")]
                
                if not active_threads and completed < total_models:
                    # If no active threads but not all models completed, some may have failed silently
                    logger.log(f"Warning: No active threads but only {completed}/{total_models} completed")
                
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
            logger.log(f"Error getting results from queue: {str(e)}")
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
                logger.log(f"Returning 1 previously processed result (total completed: {completed})")
                logger.log(f"Result data: {next_result}")
            
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
            logger.log(f"No new results to return (total completed: {completed}, active threads: {len(active_threads)})")
        
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
        logger.log(f"Error in get_model_results: {str(e)}")
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
        logger.log("get_user_analytics called by user:", request.user.username)
        
        # Get the last 30 days of evaluations
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_evaluations = ModelEvaluationHistory.objects.filter(
            created_at__gte=thirty_days_ago,
            is_active=True
        )
        
        logger.log(f"Found {recent_evaluations.count()} evaluations in the last 30 days")

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

        logger.log(f"Found {len(user_stats)} unique users with evaluations")

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
        
        logger.log(f"Returning {len(user_metrics)} user metrics")
        logger.log("Sample user metrics:", user_metrics[:2] if user_metrics else "No user metrics")

        return JsonResponse({
            'success': True,
            'user_metrics': user_metrics
        })
    except Exception as e:
        logger.log(f"Error in get_user_analytics: {str(e)}")
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
        
        logger.log(f"Saving edited response: response_id={response_id}, model_id={model_id}")
        
        if not edited_content:
            return JsonResponse({'success': False, 'error': 'Missing edited content'})
        
        # Get the current session ID from the request
        session_id = request.session.get('current_session_id')
        
        # If no session ID in the session, try to get it from the model_results keys
        if not session_id and model_results:
            # Use the most recent session ID (assuming it's the current one)
            session_id = list(model_results.keys())[-1]
            logger.log(f"Using most recent session ID: {session_id}")
            # Store it in the session for future use
            request.session['current_session_id'] = session_id
        
        # Debug information
        logger.log(f"Available sessions: {list(model_results.keys())}")
        
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
                    logger.log(f"Updated database entry for model {model_id}")
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
                        logger.log(f"Updated database entry with ID {response_id}")
                        db_updated = True
                except (ValueError, TypeError):
                    # Not a valid UUID, continue with in-memory updates
                    pass
        except Exception as db_error:
            logger.log(f"Error updating database: {str(db_error)}")
            # Continue with in-memory updates even if DB update fails
        
        # Now update the in-memory model_results as well
        memory_updated = False
        
        # Try to find the result by response_id directly
        if response_id and response_id in model_results:
            logger.log(f"Found result by response_id: {response_id}")
            model_results[response_id]['response'] = edited_content
            memory_updated = True
        
        # Try to find the result in the session by model_id
        if not memory_updated and session_id and session_id in model_results:
            logger.log(f"Checking session {session_id} with {len(model_results[session_id])} results")
            
            # Check if model_results[session_id] is a list or a dict
            if isinstance(model_results[session_id], list):
                for i, result in enumerate(model_results[session_id]):
                    logger.log(f"Comparing model_id: {result.get('model_id')} with {model_id}")
                    if str(result.get('model_id')) == str(model_id) or result.get('model_name') == model_id:
                        logger.log(f"Found match at index {i}")
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
                logger.log(f"Searching session {sess_id}")
                if isinstance(results, list):
                    for i, result in enumerate(results):
                        if str(result.get('model_id')) == str(model_id) or result.get('model_name') == model_id:
                            logger.log(f"Found match in session {sess_id} at index {i}")
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
            logger.log(f"Creating new entry in session {session_id}")
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
                logger.log(f"Created new database entry for edited response")
                db_updated = True
            except Exception as create_error:
                logger.log(f"Error creating new database entry: {str(create_error)}")
            
            memory_updated = True
        
        if memory_updated or db_updated:
            return JsonResponse({
                'success': True,
                'db_updated': db_updated,
                'memory_updated': memory_updated
            })
        
        # If we reach here, we couldn't find the result to update
        logger.log(f"Could not find response to update. response_id={response_id}, model_id={model_id}")
        return JsonResponse({
            'success': False, 
            'error': 'Could not find the response to update. Please try again.'
        })
        
    except json.JSONDecodeError as e:
        logger.log(f"JSON decode error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Invalid JSON in request'})
    except Exception as e:
        logger.log(f"Error saving edited response: {str(e)}")
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
    Reviewer: Review a question by question_id with project-specific validation criteria.
    Renders the review page with input for Google Colab link, model selection, and review UI.
    Uses project-specific criteria based on priority configuration.
    """
    from .models import TrainerTask, Project
    
    # Try to determine the project from the question_id
    # Look for a TrainerTask with this question_id to get the project
    project = None
    task = TrainerTask.objects.filter(question_id=question_id).first()
    if task and task.project:
        project = task.project
        logger.log(f"DEBUG: Found project {project.code} for question_id {question_id}")
    else:
        logger.log(f"DEBUG: No project found for question_id {question_id}")
    
    # Get project-specific validation criteria using the helper function
    project_criteria = get_project_criteria(project)
    
    # Convert to list if it's a QuerySet for easier template handling
    if hasattr(project_criteria, 'all'):
        criteria_list = list(project_criteria.all())
    else:
        criteria_list = list(project_criteria)
    
    # Debug: Print current criteria to help troubleshoot
    logger.log(f"DEBUG: review_question - Project: {project.code if project else 'None'}")
    logger.log(f"DEBUG: review_question - Found {len(criteria_list)} active criteria:")
    for i, criteria in enumerate(criteria_list):
        logger.log(f"DEBUG: review_question - Criteria {i+1}: {criteria.name}")
    
    # Fetch system messages based on user preference (stream/subject)
    preferred_streams = []
    try:
        prefs = request.user.preference
        preferred_streams = prefs.streams_and_subjects.all()
        logger.log(f"DEBUG: User {request.user.username} has {preferred_streams.count()} preferred streams")
    except Exception as e:
        preferred_streams = []
        logger.log(f"DEBUG: No user preferences found: {e}")
    
    if preferred_streams:
        system_messages = SystemMessage.objects.filter(category__in=preferred_streams).order_by('name')
        logger.log(f"DEBUG: Found {system_messages.count()} system messages for preferred streams")
    else:
        # Default to "Coding" stream if exists, else all
        coding_messages = SystemMessage.objects.filter(category__name__icontains="coding").order_by('name')
        if coding_messages.exists():
            system_messages = coding_messages
            logger.log(f"DEBUG: Using {system_messages.count()} coding-related system messages")
        else:
            system_messages = SystemMessage.objects.all().order_by('name')
            logger.log(f"DEBUG: Using all {system_messages.count()} system messages")
    
    # Fetch project-tied LLM models if project exists, else global
    from .models import ProjectLLMModel
    if project:
        project_llm_models = ProjectLLMModel.objects.filter(project=project).select_related('llm_model')
        if project_llm_models.exists():
            llm_models = project_llm_models.filter(is_active=True).order_by('llm_model__name')
        else:
            llm_models = LLMModel.objects.filter(is_active=True, is_default=True).order_by('name')
            if not llm_models.exists():
                llm_models = LLMModel.objects.filter(is_active=True).order_by('name')
    else:
        llm_models = LLMModel.objects.filter(is_active=True).order_by('name')
    logger.log(f"DEBUG: Found {llm_models.count()} active LLM models (project-tied or global)")
    
    # Debug: Print first few system messages
    for i, sm in enumerate(system_messages[:3]):
        logger.log(f"DEBUG: System message {i+1}: {sm.name} - {sm.content[:50]}...")
    
    # Debug: Print project-specific criteria
    logger.log(f"DEBUG: Project: {project.code if project else 'None'}")
    logger.log(f"DEBUG: Active criteria count: {len(criteria_list)}")
    for i, criteria in enumerate(criteria_list):
        logger.log(f"DEBUG: Criteria {i+1}: {criteria.name}")
    
    context = {
        "question_id": question_id,
        "project": project,
        "project_criteria": criteria_list,
        "system_messages": system_messages,
        "llm_models": llm_models,
    }
    return render(request, "review.html", context)

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

@login_required
def get_llm_job_stats(request):
    """Get LLM job statistics for the dashboard."""
    try:
        from .models import LLMJob
        from django.db.models import Count
        
        # Get job counts by status
        status_counts = dict(
            LLMJob.objects.values('status').annotate(count=Count('status')).values_list('status', 'count')
        )
        
        # Get total job count
        total_jobs = LLMJob.objects.count()
        
        return JsonResponse({
            'success': True,
            'total_jobs': total_jobs,
            'status_counts': status_counts
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# Activity Tracking API Endpoints
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
@login_required
def activity_start(request):
    """Start a new activity tracking session."""
    try:
        from .models import UserActivitySession
        import json
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            # Handle FormData from sendBeacon
            data_str = request.POST.get('data')
            if data_str:
                data = json.loads(data_str)
            else:
                data = request.POST.dict()
        
        session_id = data.get('session_id')
        activity_type = data.get('activity_type', 'unknown')
        
        if not session_id:
            return JsonResponse({'success': False, 'error': 'Missing session_id'})
        
        # Create new activity session
        session = UserActivitySession.objects.create(
            user=request.user,
            session_id=session_id,
            activity_type=activity_type,
            session_start=timezone.now(),
            focus_time_minutes=0,
            page_interactions=0
        )
        
        return JsonResponse({
            'success': True,
            'session_id': session.session_id
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@require_POST
@login_required
def activity_update(request):
    """Update an existing activity tracking session."""
    try:
        from .models import UserActivitySession
        import json
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            # Handle FormData from sendBeacon
            data_str = request.POST.get('data')
            if data_str:
                data = json.loads(data_str)
            else:
                data = request.POST.dict()
        
        session_id = data.get('session_id')
        focus_time_minutes = int(data.get('focus_time_minutes', 0))
        interactions = int(data.get('interactions', 0))
        is_active = data.get('is_active', True)
        
        if not session_id:
            return JsonResponse({'success': False, 'error': 'Missing session_id'})
        
        # Update existing session
        try:
            session = UserActivitySession.objects.get(
                user=request.user,
                session_id=session_id,
                session_end__isnull=True  # Only update active sessions
            )
            
            session.focus_time_minutes = focus_time_minutes
            session.interactions = interactions
            session.is_active = is_active
            session.last_activity = timezone.now()
            session.save()
            
            return JsonResponse({'success': True})
            
        except UserActivitySession.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Session not found or already ended'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@require_POST
@login_required
def activity_end(request):
    """End an activity tracking session."""
    try:
        from .models import UserActivitySession
        import json
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            # Handle FormData from sendBeacon
            data_str = request.POST.get('data')
            if data_str:
                data = json.loads(data_str)
            else:
                data = request.POST.dict()
        
        session_id = data.get('session_id')
        focus_time_minutes = int(data.get('focus_time_minutes', 0))
        interactions = int(data.get('interactions', 0))
        
        if not session_id:
            return JsonResponse({'success': False, 'error': 'Missing session_id'})
        
        # End the session
        try:
            session = UserActivitySession.objects.get(
                user=request.user,
                session_id=session_id,
                session_end__isnull=True  # Only end active sessions
            )
            
            session.focus_time_minutes = focus_time_minutes
            session.interactions = interactions
            session.session_end = timezone.now()
            session.is_active = False
            session.save()
            
            return JsonResponse({'success': True})
            
        except UserActivitySession.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Session not found or already ended'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@role_required(['admin'])
def project_config_view(request):
    """
    Admin-only view for configuring project-specific validation criteria.
    Allows enabling/disabling validation criteria for each project.
    """
    from .models import Project, Validation, ProjectCriteria
    import json
    
    # Get all active projects and validations
    projects = Project.objects.filter(is_active=True).order_by('name')
    validations = Validation.objects.filter(is_active=True).order_by('name')
    
    selected_project_id = request.GET.get('project')
    selected_project = None
    project_criteria = []
    
    if selected_project_id:
        try:
            selected_project = Project.objects.get(id=selected_project_id, is_active=True)
            
            # Get existing criteria settings for this project
            existing_criteria = {
                pc.validation_id: pc for pc in 
                ProjectCriteria.objects.filter(project=selected_project).select_related('validation')
            }
            
            # Build criteria list with current settings
            for validation in validations:
                if validation.validation_id in existing_criteria:
                    # Use existing setting
                    criteria_obj = existing_criteria[validation.validation_id]
                    project_criteria.append({
                        'validation': validation,
                        'is_enabled': criteria_obj.is_enabled,
                        'priority': criteria_obj.priority,
                        'has_setting': True
                    })
                else:
                    # Default setting (enabled)
                    project_criteria.append({
                        'validation': validation,
                        'is_enabled': True,
                        'priority': 1,
                        'has_setting': False
                    })
            # Fetch project LLM modals for this project
            from .models import ProjectLLMModel
            project_llm_modals = list(ProjectLLMModel.objects.filter(project=selected_project).select_related('llm_model').order_by('llm_model__name'))
        except Project.DoesNotExist:
            selected_project = None
            project_llm_modals = []
    
    # Calculate statistics
    total_projects = projects.count()
    total_validations = validations.count()
    configured_projects = ProjectCriteria.objects.values('project').distinct().count()
    
    context = {
        'projects': projects,
        'validations': validations,
        'selected_project': selected_project,
        'project_criteria': project_criteria,
        'project_llm_modals': project_llm_modals if selected_project_id else [],
        'stats': {
            'total_projects': total_projects,
            'total_validations': total_validations,
            'configured_projects': configured_projects,
        }
    }
    
    return render(request, 'project_config.html', context)


@require_POST
@login_required
@role_required(['admin'])
def update_project_criteria(request):
    """
    AJAX endpoint to update project criteria settings.
    """
    try:
        from .models import Project, Validation, ProjectCriteria
        import json
        
        data = json.loads(request.body)
        project_id = data.get('project_id')
        validation_id = data.get('validation_id')
        is_enabled = data.get('is_enabled', True)
        priority = data.get('priority', 1)
        
        if not project_id or not validation_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing project_id or validation_id'
            })
        
        try:
            project = Project.objects.get(id=project_id, is_active=True)
            validation = Validation.objects.get(validation_id=validation_id, is_active=True)
        except (Project.DoesNotExist, Validation.DoesNotExist):
            return JsonResponse({
                'success': False,
                'error': 'Project or validation not found'
            })
        
        # Update or create the criteria setting
        criteria, created = ProjectCriteria.objects.update_or_create(
            project=project,
            validation=validation,
            defaults={
                'is_enabled': is_enabled,
                'priority': priority
            }
        )
        
        return JsonResponse({
            'success': True,
            'created': created,
            'message': f'{"Created" if created else "Updated"} criteria setting for {project.code} - {validation.name}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@require_POST
@login_required
@role_required(['admin'])
def bulk_update_project_criteria(request):
    """
    AJAX endpoint to bulk update project criteria (enable/disable all).
    """
    try:
        from .models import Project, Validation, ProjectCriteria
        import json
        
        data = json.loads(request.body)
        project_id = data.get('project_id')
        action = data.get('action')  # 'enable_all' or 'disable_all' or 'reset_defaults'
        
        if not project_id or not action:
            return JsonResponse({
                'success': False,
                'error': 'Missing project_id or action'
            })
        
        try:
            project = Project.objects.get(id=project_id, is_active=True)
        except Project.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Project not found'
            })
        
        validations = Validation.objects.filter(is_active=True)
        updated_count = 0
        
        if action == 'enable_all':
            for validation in validations:
                criteria, created = ProjectCriteria.objects.update_or_create(
                    project=project,
                    validation=validation,
                    defaults={'is_enabled': True, 'priority': 1}
                )
                updated_count += 1
                
        elif action == 'disable_all':
            for validation in validations:
                criteria, created = ProjectCriteria.objects.update_or_create(
                    project=project,
                    validation=validation,
                    defaults={'is_enabled': False, 'priority': 1}
                )
                updated_count += 1
                
        elif action == 'reset_defaults':
            # Delete all custom settings (will fall back to defaults)
            deleted_count = ProjectCriteria.objects.filter(project=project).delete()[0]
            updated_count = deleted_count
        
        return JsonResponse({
            'success': True,
            'updated_count': updated_count,
            'message': f'Bulk action "{action}" completed for {updated_count} criteria'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@require_POST
@login_required
@role_required(['admin'])
def update_project_llm_modal(request):
    """
    AJAX endpoint to enable/disable a ProjectLLMModel (LLM modal) for a project.
    """
    try:
        from .models import ProjectLLMModel
        import json

        data = json.loads(request.body)
        modal_id = data.get('project_llm_modal_id')
        is_active = data.get('is_active')

        if modal_id is None or is_active is None:
            return JsonResponse({'success': False, 'error': 'Missing project_llm_modal_id or is_active'})

        try:
            modal = ProjectLLMModel.objects.get(id=modal_id)
        except ProjectLLMModel.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'LLM modal not found'})

        modal.is_active = bool(is_active)
        modal.save()

        return JsonResponse({'success': True, 'message': f'LLM modal "{modal.llm_model.name}" has been {"enabled" if modal.is_active else "disabled"} for this project.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_POST
@login_required
@role_required(['admin'])
def update_user_role(request):
    """
    AJAX endpoint to update a user's role (group membership).
    Only admins can access this endpoint.
    """
    try:
        import json
        from django.contrib.auth.models import User, Group
        
        data = json.loads(request.body)
        user_id = data.get('user_id')
        new_role = data.get('new_role')
        
        if not user_id or not new_role:
            return JsonResponse({
                'success': False,
                'error': 'Missing user_id or new_role'
            })
        
        # Validate the new role
        valid_roles = ['trainer', 'pod_lead', 'admin']
        if new_role not in valid_roles:
            return JsonResponse({
                'success': False,
                'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'
            })
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'User not found'
            })
        
        # Don't allow changing superuser roles
        if user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'Cannot change superuser roles'
            })
        
        try:
            # Get the new group
            new_group = Group.objects.get(name=new_role)
        except Group.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Group "{new_role}" does not exist'
            })
        
        # Remove user from all existing groups (to ensure single role)
        user.groups.clear()
        
        # Add user to the new group
        user.groups.add(new_group)
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully updated {user.username}\'s role to {new_role}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@require_http_methods(["GET"])
@login_required
def sync_status_api(request):
    """
    API endpoint to get real-time sync daemon status information.
    Returns configuration details, timing, and next sync schedules.
    """
    try:
        from .models import TaskSyncConfig
        from django.utils import timezone
        from datetime import timedelta
        
        # Get all active sync configurations
        configs = TaskSyncConfig.objects.filter(is_active=True).select_related('project')
        
        configurations = []
        current_time = timezone.now()
        
        for config in configs:
            # Calculate time since last sync
            time_since_last_sync = None
            if config.last_synced:
                time_since_last_sync = current_time - config.last_synced
            
            # Calculate next sync time
            next_sync_time = None
            next_sync_seconds = None
            should_sync_now = False
            
            if config.last_synced and config.sync_interval_minutes:
                next_sync_time = config.last_synced + timedelta(minutes=config.sync_interval_minutes)
                time_until_next_sync = next_sync_time - current_time
                next_sync_seconds = int(time_until_next_sync.total_seconds())
                
                # Check if sync is overdue
                should_sync_now = next_sync_seconds <= 0
                
                # Format next sync display
                if should_sync_now:
                    next_sync_in = "Overdue"
                else:
                    # Format as human readable
                    hours = next_sync_seconds // 3600
                    minutes = (next_sync_seconds % 3600) // 60
                    seconds = next_sync_seconds % 60
                    
                    if hours > 0:
                        next_sync_in = f"{hours}h {minutes}m {seconds}s"
                    elif minutes > 0:
                        next_sync_in = f"{minutes}m {seconds}s"
                    else:
                        next_sync_in = f"{seconds}s"
            else:
                next_sync_in = "Never synced"
                should_sync_now = True
            
            # Format last synced time
            if time_since_last_sync:
                total_seconds = int(time_since_last_sync.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                secs = total_seconds % 60
                
                if hours > 0:
                    last_synced_ago = f"{hours}h {minutes}m {secs}s ago"
                elif minutes > 0:
                    last_synced_ago = f"{minutes}m {secs}s ago"
                else:
                    last_synced_ago = f"{secs}s ago"
            else:
                last_synced_ago = "Never"
            
            config_data = {
                'project_code': config.project.code if config.project else 'Unknown',
                'project_name': config.project.name if config.project else 'Unknown',
                'sheet_url': config.sheet_url,
                'sync_interval_minutes': config.sync_interval_minutes,
                'is_active': config.is_active,
                'last_synced': config.last_synced.isoformat() if config.last_synced else None,
                'last_synced_ago': last_synced_ago,
                'should_sync_now': should_sync_now,
                'next_sync_in': next_sync_in,
                'next_sync_seconds': max(0, next_sync_seconds) if next_sync_seconds is not None else 0,
                'primary_key_column': config.primary_key_column,
                'sync_mode': config.sync_mode,
                'scraping_needed': config.scraping_needed
            }
            
            configurations.append(config_data)
        
        return JsonResponse({
            'success': True,
            'timestamp': current_time.isoformat(),
            'total_configurations': len(configurations),
            'configurations': configurations
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


def get_project_criteria(project):
    """
    Helper function to get enabled validation criteria for a project.
    Returns all active validations by default if no project found.
    If project found, returns all active validations EXCEPT those explicitly disabled.
    If all criteria are disabled for a project, falls back to a minimal default set.
    Results are ordered by priority (lower numbers first), then by name.
    """
    from .models import Validation, ProjectCriteria
    
    if not project:
        # No project found, return all active validations as default
        return Validation.objects.filter(is_active=True).order_by('name')
    
    # Get all active validations
    all_validations = Validation.objects.filter(is_active=True)
    
    # Get explicit project criteria settings for this project
    project_criteria_settings = ProjectCriteria.objects.filter(project=project).select_related('validation')
    
    if project_criteria_settings.exists():
        # Project has explicit criteria settings
        # Create a mapping of validation_id to ProjectCriteria
        criteria_map = {pc.validation.validation_id: pc for pc in project_criteria_settings}
        
        enabled_criteria = []
        for validation in all_validations:
            if validation.validation_id in criteria_map:
                # Use explicit setting - only include if enabled
                pc = criteria_map[validation.validation_id]
                if pc.is_enabled:
                    enabled_criteria.append((validation, pc.priority))
            else:
                # No explicit setting, default to enabled
                enabled_criteria.append((validation, 1))  # Default priority
        
        # Check if no criteria are enabled (edge case)
        if not enabled_criteria:
            logger.log(f"WARNING: No criteria enabled for project {project.code}. Using minimal fallback set.")
            # Fallback to a minimal essential set - at least Grammar Check and Code Quality
            fallback_criteria = all_validations.filter(
                name__in=['Grammar Check', 'Code Style Check', 'Logic Validation']
            ).order_by('name')
            
            if fallback_criteria.exists():
                return list(fallback_criteria)
            else:
                # Ultimate fallback - return the first available validation
                first_validation = all_validations.first()
                return [first_validation] if first_validation else []
        
        # Sort by priority (ascending), then by name
        enabled_criteria.sort(key=lambda x: (x[1], x[0].name))
        
        # Return just the validation objects in the correct order
        return [criteria[0] for criteria in enabled_criteria]
    else:
        # No explicit project criteria settings exist, return all active validations
        return all_validations.order_by('name')
