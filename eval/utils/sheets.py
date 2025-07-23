import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Google Sheets settings
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), '../../service_account.json')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# The spreadsheet ID and range name
SPREADSHEET_ID = '1H8DEeeH7GGoOknkM5t9eOBuEVbNZBvkA3EinokkuAfM'
RANGE_NAME = 'prompts'  # Change if your sheet/tab has a different name

def fetch_trainer_tasks():
    """
    Fetches the trainer task assignments from the Google Sheet.
    Returns a list of dictionaries, one per row.
    """
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('sheets', 'v4', credentials=credentials)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    values = result.get('values', [])

    if not values or len(values) < 2:
        return []

    # First row is header
    headers = values[0]
    tasks = []
    for row in values[1:]:
        # Pad row to match headers
        row += [''] * (len(headers) - len(row))
        task = dict(zip(headers, row))
        tasks.append(task)
    return tasks

def sync_trainer_tasks(config, selected_project=None, sync_type="auto", synced_by="system"):
    """
    Syncs TrainerTask objects from the Google Sheet specified in config.
    Uses config-driven mapping for primary key, columns, and scraping.
    Logs the sync in TaskSyncHistory and updates config.last_synced.
    Returns (status, summary, details, created_count, updated_count, deleted_count)
    """
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from eval.models import TrainerTask, TaskSyncHistory
    from django.utils import timezone

    created_count = updated_count = deleted_count = 0
    sync_status = "success"
    sync_summary = ""
    sync_details = ""

    import os
    try:
        print("DEBUG: sync_trainer_tasks running as UID:", os.getuid(), "EUID:", os.geteuid())
        print("DEBUG: Database path:", os.path.abspath(config._meta.get_field('project').model._meta.app_config.path))
        sync_mode = config.sync_mode or "prompt_in_sheet"
        if sync_mode == "custom":
            # --- Custom sync logic placeholder ---
            # Example: Only sync rows where "Status" column is "Ready"
            SERVICE_ACCOUNT_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../service_account.json'))
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_url(config.sheet_url)
            worksheet = sheet.get_worksheet(0)
            rows = worksheet.get_all_values()
            headers = rows[0]
            data_rows = rows[1:]

            primary_key = config.primary_key_column or "question_id"
            mapping = config.column_mapping or {}

            sheet_keys = set()
            for row in data_rows:
                row_dict = dict(zip(headers, row))
                if row_dict.get("Status") != "Ready":
                    continue
                pk_value = row_dict.get(primary_key) or row_dict.get(primary_key.replace("_", " ")) or row_dict.get(primary_key.replace("_", " ").title())
                if not pk_value:
                    continue
                sheet_keys.add(pk_value)
                defaults = {}
                for logical_field, sheet_col in mapping.items():
                    value = row_dict.get(sheet_col)
                    if value is not None:
                        defaults[logical_field] = value
                defaults["project"] = selected_project
                if "prompt" in defaults:
                    defaults["raw_prompt"] = defaults["prompt"]
                filter_kwargs = {primary_key: pk_value}
                obj, created = TrainerTask.objects.update_or_create(
                    **filter_kwargs,
                    defaults=defaults
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            # Delete tasks not in the sheet for this project
            if selected_project:
                filter_kwargs = {"project": selected_project}
                filter_kwargs[primary_key + "__isnull"] = False
                to_delete = TrainerTask.objects.filter(**filter_kwargs).exclude(**{primary_key + "__in": list(sheet_keys)})
                deleted_count = to_delete.count()
                to_delete.delete()
            sync_summary = f"{created_count} created, {updated_count} updated, {deleted_count} deleted (custom sync)"
        else:
            # Use the service account json if available
            SERVICE_ACCOUNT_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../service_account.json'))
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_url(config.sheet_url)
            worksheet = sheet.get_worksheet(0)
            rows = worksheet.get_all_values()
            headers = rows[0]
            data_rows = rows[1:]

            # Config-driven fields
            primary_key = config.primary_key_column or "question_id"
            mapping = config.column_mapping or {}
            scraping_needed = config.scraping_needed
            link_column = config.link_column

            # Build a set of primary keys from the sheet
            sheet_keys = set()
            for row in data_rows:
                row_dict = dict(zip(headers, row))
                
                # First try to get primary key from column mapping, then fallback to direct lookup
                mapped_pk_column = mapping.get(primary_key, primary_key)
                pk_value = row_dict.get(mapped_pk_column)
                if not pk_value:
                    # Fallback to original logic
                    pk_value = row_dict.get(primary_key) or row_dict.get(primary_key.replace("_", " ")) or row_dict.get(primary_key.replace("_", " ").title())
                if not pk_value:
                    continue
                sheet_keys.add(pk_value)

                # Get or create the task
                filter_kwargs = {primary_key: pk_value}
                obj, created = TrainerTask.objects.get_or_create(**filter_kwargs, defaults={"project": selected_project})
                
                # Update all fields using the flexible field methods
                obj.project = selected_project
                
                # Handle mapped fields
                for logical_field, sheet_col in mapping.items():
                    value = row_dict.get(sheet_col, '')
                    if value is not None:
                        obj.set_field_value(logical_field, value)
                
                # Handle unmapped fields (store in dynamic_fields)
                for sheet_col, value in row_dict.items():
                    # Skip if this column is already mapped or is empty
                    if sheet_col in mapping.values() or not value:
                        continue
                    # Convert sheet column name to a logical field name
                    logical_field = sheet_col.lower().replace(' ', '_').replace('-', '_')
                    obj.set_field_value(logical_field, value)
                
                # Scraping logic (if needed)
                if scraping_needed and link_column and row_dict.get(link_column):
                    obj.set_field_value("raw_prompt", f"[TO SCRAPE] {row_dict.get(link_column)}")
                elif mapping.get("prompt"):
                    # If prompt is mapped, also set raw_prompt
                    prompt_value = obj.get_field_value("prompt")
                    if prompt_value:
                        obj.set_field_value("raw_prompt", prompt_value)
                
                obj.save()
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            # Delete tasks not in the sheet for this project
            if selected_project:
                filter_kwargs = {"project": selected_project}
                filter_kwargs[primary_key + "__isnull"] = False
                to_delete = TrainerTask.objects.filter(**filter_kwargs).exclude(**{primary_key + "__in": list(sheet_keys)})
                deleted_count = to_delete.count()
                to_delete.delete()
            sync_summary = f"{created_count} created, {updated_count} updated, {deleted_count} deleted"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("SYNC ERROR:", str(e))
        print("TRACEBACK:", tb)
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
        sync_type=sync_type,
        synced_by=synced_by,
    )
    config.last_synced = timezone.now()
    config.save()
    return sync_status, sync_summary, sync_details, created_count, updated_count, deleted_count
