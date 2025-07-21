# processor/utils.py
import os
import csv
import json
import tempfile
import sqlite3
from django.contrib.auth.models import User, Group, Permission
from .download import main as download_notebooks
from .converter import convert_file_to_json
from openai import OpenAI
from fireworks.client import Fireworks
from .logger import log_message
from .models import Prompt, LLMModel
from django.conf import settings


def process_csv_and_evaluate(csv_file, openai_api_key, model, prompt, request):
    analysis_results = []
    processing_steps = []
    upload_filename = csv_file.name  # save the original filename

    try:
        log_message("Starting CSV processing...")
        
        # Save uploaded CSV to a temporary file with filename info
        processing_steps.append({
            "title": "CSV Upload",
            "status": "Processing",
            "details": "Saving uploaded CSV file",
            "filename": upload_filename  # use consistent key
        })
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
            for chunk in csv_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
            
        processing_steps[-1]["status"] = "Complete"
        log_message("Reading CSV file...")

        try:
            # Download notebooks from Google Drive
            processing_steps.append({
                "title": "Google Drive Download",
                "status": "Processing",
                "details": "Downloading notebooks from Google Drive",
                "filename": upload_filename
            })
            download_notebooks(tmp_path, request)
            processing_steps[-1]["status"] = "Complete"
            # Process downloaded Python files
            download_dir = os.path.join("./processor/download_container", request.user.username)
            
            # Create user-specific directory if it doesn't exist
            os.makedirs(download_dir, exist_ok=True)
            for py_filename in os.listdir(download_dir):
                if py_filename.endswith('.py'):
                    processing_steps.append({
                        "title": "File Conversion",
                        "filename": py_filename,  # changed key here
                        "status": "Processing",
                        "details": "Converting Python file to JSON format"
                    })
                    
                    file_path = os.path.join(download_dir, py_filename)
                    json_output_path = os.path.join(download_dir, f"{os.path.splitext(py_filename)[0]}.json")
                    
                    # Convert Python file to JSON
                    result = convert_file_to_json(file_path, json_output_path)
                    processing_steps[-1]["status"] = "Complete"
                    
                    if result:
                        processing_steps.append({
                            "title": "LLM Analysis",
                            "filename": py_filename,  # changed key here
                            "status": "Processing",
                            "details": "Analyzing with OpenAI or DeepSeek"
                        })
                        
                        # Analyze with the appropriate LLM
                        analysis = evaluate_with_llm(result, openai_api_key, model, prompt)
                        analysis_results.append({
                            "file_name": py_filename,
                            "analysis": analysis
                        })
                        processing_steps[-1]["status"] = "Complete"

        finally:
            # Cleanup
            processing_steps.append({
                "title": "Cleanup",
                "status": "Processing",
                "details": "Removing temporary files",
                "filename": upload_filename
            })
            os.remove(tmp_path)
            processing_steps[-1]["status"] = "Complete"
            
        log_message("CSV processing completed")
        return analysis_results, processing_steps
        
    except Exception as e:
        log_message(f"Error in process_csv_and_evaluate: {str(e)}")
        raise

def evaluate_with_llm(json_result, openai_api_key, model, prompt):
    # Default to OpenAI client
    client = OpenAI(
        api_key=openai_api_key,
        base_url=getattr(settings, "OPENAI_API_URL", "https://api.openai.com/v1")
    )
    
    # Handle DeepSeek models
    if 'deepseek' in model.name.lower():
        from django.conf import settings
        deepseek_key = settings.DEEPSEEK_API_KEY.strip("'\"")
        client = OpenAI(
            api_key=deepseek_key,
            base_url=settings.DEEPSEEK_API_URL
        )
        log_message(f"DeepSeek client initialized with base URL: {settings.DEEPSEEK_API_URL}")

    # Handle LLaMA models with Fireworks
    if 'llama' in model.name.lower():
        from django.conf import settings
        try:
            client = Fireworks(api_key=settings.FIREWORKS_API, base_url=settings.FIREWORKS_API_URL)
            log_message(f"Fireworks client initialized with base URL: {settings.FIREWORKS_API_URL}")
        except TypeError:
            client = Fireworks(api_key=settings.FIREWORKS_API)
            log_message(f"Fireworks client initialized with default base URL (FIREWORKS_API_URL not supported by client)")
        # Use the confirmed working model name
        model.name = "accounts/fireworks/models/" + model.name 
        log_message(f"Using Fireworks Llama model: {model.name}")
        print("Updated model name:", model.name)
        print("***************************************")
    else:
        log_message(f"Using standard client for model: {model.name}")

    # Get the system message from the Prompt object
    system_message = prompt.system_message

    # Extract logical reasoning sections from the JSON result
    reasoning = json_result.get("messages", [{}])[1].get("reasoning", {}).get("process", [])

    # Create a prompt combining instructions with the reasoning sections
    user_prompt = (
        f"Evaluate whether the following section logically follows the preceding section in terms of context and flow. "
        f"Identify any gaps, inconsistencies, or abrupt transitions.\n\n"
        f"Sections:\n{json.dumps(reasoning, indent=2)}"
    )

    try:
        params = {
            "model": model.name,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False
        }
        if hasattr(model, 'temperature') and model.temperature is not None:
            params["temperature"] = model.temperature
        
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content.strip()
    except Exception as e:
        log_message(f"LLM evaluation error: {str(e)}")
        return f"LLM evaluation error: {str(e)}"


def import_users_from_backup(backup_path):
    """
    Import users and their permissions from a backup SQLite database.
    
    Args:
        backup_path (str): Path to the backup SQLite database file.
        
    Returns:
        tuple: (success, message) where success is a boolean and message contains details about the operation.
    """
    try:
        if not os.path.exists(backup_path):
            error_msg = f"Backup file not found at {backup_path}"
            log_message(error_msg)
            return False, error_msg
            
        # Connect to the backup database
        backup_conn = sqlite3.connect(backup_path)
        backup_cursor = backup_conn.cursor()
        
        # Get users from backup
        backup_cursor.execute("""
            SELECT id, username, password, email, is_superuser, is_staff, is_active, date_joined, first_name, last_name
            FROM auth_user
        """)
        users_data = backup_cursor.fetchall()
        
        # Get user permissions from backup
        backup_cursor.execute("""
            SELECT user_id, permission_id
            FROM auth_user_user_permissions
        """)
        user_permissions_data = backup_cursor.fetchall()
        
        # Get user groups from backup
        backup_cursor.execute("""
            SELECT user_id, group_id
            FROM auth_user_groups
        """)
        user_groups_data = backup_cursor.fetchall()
        
        # Close backup database connection
        backup_conn.close()
        
        # Import users
        users_imported = 0
        users_updated = 0
        
        for user_data in users_data:
            user_id, username, password, email, is_superuser, is_staff, is_active, date_joined, first_name, last_name = user_data
            
            # Check if user already exists
            try:
                user = User.objects.get(username=username)
                # Update existing user
                user.email = email
                user.is_superuser = bool(is_superuser)
                user.is_staff = bool(is_staff)
                user.is_active = bool(is_active)
                user.first_name = first_name
                user.last_name = last_name
                user.save()
                users_updated += 1
            except User.DoesNotExist:
                # Create new user
                user = User.objects.create(
                    username=username,
                    email=email,
                    is_superuser=bool(is_superuser),
                    is_staff=bool(is_staff),
                    is_active=bool(is_active),
                    first_name=first_name,
                    last_name=last_name
                )
                # Set password hash directly
                user.password = password
                user.save()
                users_imported += 1
        
        # Import user permissions
        permissions_added = 0
        for user_id, permission_id in user_permissions_data:
            try:
                user = User.objects.get(id=user_id)
                permission = Permission.objects.get(id=permission_id)
                if not user.user_permissions.filter(id=permission_id).exists():
                    user.user_permissions.add(permission)
                    permissions_added += 1
            except (User.DoesNotExist, Permission.DoesNotExist):
                continue
        
        # Import user groups
        groups_added = 0
        for user_id, group_id in user_groups_data:
            try:
                user = User.objects.get(id=user_id)
                group = Group.objects.get(id=group_id)
                if not user.groups.filter(id=group_id).exists():
                    user.groups.add(group)
                    groups_added += 1
            except (User.DoesNotExist, Group.DoesNotExist):
                continue
        
        success_msg = f"Successfully imported {users_imported} users, updated {users_updated} users, "
        success_msg += f"added {permissions_added} permissions and {groups_added} group memberships."
        log_message(success_msg)
        return True, success_msg
        
    except Exception as e:
        error_msg = f"Error importing users from backup: {str(e)}"
        log_message(error_msg)
        return False, error_msg
