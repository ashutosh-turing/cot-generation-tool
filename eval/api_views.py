from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from django.core.cache import cache
from eval.models import LLMModel

@csrf_exempt
def fetch_colab_content(request):
    """
    API endpoint to fetch and return the content of a Google Colab notebook as markdown/plain text.
    Expects a JSON payload with:
    - file_id: The Google Drive file ID of the Colab notebook
    """
    import os, io, json as pyjson
    from django.conf import settings
    try:
        if request.method != "POST":
            return JsonResponse({"success": False, "error": "Invalid request method."})
        data = json.loads(request.body)
        file_id = data.get('file_id')
        if not file_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameter: file_id'
            }, status=400)
        SERVICE_ACCOUNT_FILE = os.path.join(settings.BASE_DIR, 'service_account.json')
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            return JsonResponse({
                'success': False,
                'error': 'Service account file not found. Please ensure service_account.json is in the project root directory.'
            }, status=500)
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        import nbformat
        SCOPES = ['https://www.googleapis.com/auth/drive']
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        drive_service = build('drive', 'v3', credentials=credentials)
        # Download the notebook file from Drive
        try:
            drive_request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, drive_request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            nb_json = pyjson.loads(fh.read().decode('utf-8'))
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error downloading notebook: {str(e)}'
            }, status=500)
        # Parse the notebook and extract markdown and code cells
        try:
            nb = nbformat.reads(pyjson.dumps(nb_json), as_version=4)
            content_lines = []
            for cell in nb['cells']:
                if cell['cell_type'] == 'markdown':
                    content_lines.append(cell['source'])
                elif cell['cell_type'] == 'code':
                    content_lines.append(f"```python\n{cell['source']}\n```")
            content = "\n\n".join(content_lines)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error parsing notebook: {str(e)}'
            }, status=500)
        return JsonResponse({
            'success': True,
            'content': content
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }, status=500)



@csrf_exempt
def transfer_to_colab(request):
    """
    API endpoint to transfer markdown content to a Google Colab notebook.
    Expects a JSON payload with:
    - file_id: The Google Drive file ID of the Colab notebook
    - markdown_content: The markdown content to add to the notebook
    - multiple_cells: Whether to split the content into multiple cells
    - cell_separator: The separator to use when splitting the content
    """
    import os, io, json as pyjson
    from django.conf import settings
    try:
        if request.method != "POST":
            return JsonResponse({"success": False, "error": "Invalid request method."})
        data = json.loads(request.body)
        file_id = data.get('file_id')
        markdown_content = data.get('markdown_content')
        multiple_cells = data.get('multiple_cells', False)
        cell_separator = data.get('cell_separator', '---')
        if not file_id or not markdown_content:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters: file_id or markdown_content'
            }, status=400)
        SERVICE_ACCOUNT_FILE = os.path.join(settings.BASE_DIR, 'service_account.json')
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            return JsonResponse({
                'success': False,
                'error': 'Service account file not found. Please ensure service_account.json is in the project root directory.'
            }, status=500)
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
        import nbformat
        SCOPES = ['https://www.googleapis.com/auth/drive']
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        drive_service = build('drive', 'v3', credentials=credentials)
        # STEP 1: Download the current notebook file from Drive
        try:
            drive_request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, drive_request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            nb_json = pyjson.loads(fh.read().decode('utf-8'))
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error downloading notebook: {str(e)}'
            }, status=500)
        # STEP 2: Parse and modify the notebook using nbformat
        try:
            nb = nbformat.reads(pyjson.dumps(nb_json), as_version=4)
            updated = False
            if multiple_cells and cell_separator in markdown_content:
                cell_contents = markdown_content.split(cell_separator)
                cell_contents = [content.strip() for content in cell_contents if content.strip()]
                update_index = None
                for i, cell in enumerate(nb['cells']):
                    if cell['cell_type'] == 'markdown' and cell.get('metadata', {}).get('UPDATE_ME'):
                        update_index = i
                        break
                if update_index is not None:
                    nb['cells'][update_index]['source'] = cell_contents[0]
                    for i, content in enumerate(cell_contents[1:]):
                        new_cell = nbformat.v4.new_markdown_cell(source=content)
                        nb['cells'].insert(update_index + i + 1, new_cell)
                    updated = True
                else:
                    for content in cell_contents:
                        new_cell = nbformat.v4.new_markdown_cell(source=content)
                        if content == cell_contents[0]:
                            new_cell['metadata']['UPDATE_ME'] = True
                        nb['cells'].append(new_cell)
                    updated = True
            else:
                for cell in nb['cells']:
                    if cell['cell_type'] == 'markdown' and cell.get('metadata', {}).get('UPDATE_ME'):
                        cell['source'] = markdown_content
                        updated = True
                        break
                if not updated:
                    new_cell = nbformat.v4.new_markdown_cell(source=markdown_content)
                    new_cell['metadata']['UPDATE_ME'] = True
                    nb['cells'].append(new_cell)
            updated_nb_str = nbformat.writes(nb, version=4)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error updating notebook content: {str(e)}'
            }, status=500)
        # STEP 3: Update the notebook file on Google Drive
        try:
            updated_stream = io.BytesIO(updated_nb_str.encode('utf-8'))
            media_body = MediaIoBaseUpload(updated_stream, mimetype='application/json')
            updated_file = drive_service.files().update(
                fileId=file_id,
                media_body=media_body,
                fields='id',
                supportsAllDrives=True
            ).execute()
            return JsonResponse({
                'success': True,
                'file_id': updated_file.get('id'),
                'message': 'Notebook updated successfully'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error updating notebook on Drive: {str(e)}'
            }, status=500)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }, status=500)
