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

    try:
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
        sync_type=sync_type,
        synced_by=synced_by,
    )
    config.last_synced = timezone.now()
    config.save()
    return sync_status, sync_summary, sync_details, created_count, updated_count, deleted_count
