import os
import io
import csv
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from .logger import log_message
from .models import User

# Google Drive API Scope (Read-only)
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
csv_file = "/content/march3 - Sheet1 (2).csv"
# Set the output folder based on the user's username


def extract_file_id(colab_link: str) -> str:
    """Extract the file ID from a Colab link."""
    if "colab.research.google.com/drive/" in colab_link:
        parts = colab_link.split("/drive/")
        if len(parts) > 1:
            return parts[1].split("?")[0]
    return None

def download_colab_notebook(file_id: str, service, output_folder: str):
    """Download a Colab notebook (.ipynb) by file_id from Google Drive."""
    os.makedirs(output_folder, exist_ok=True)
    file_metadata = service.files().get(fileId=file_id, fields="name").execute()
    original_filename = file_metadata.get("name", file_id)

    if not original_filename.endswith(".ipynb"):
        original_filename += ".ipynb"

    output_path = os.path.join(output_folder, original_filename)
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False

    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"Downloading {original_filename}: {int(status.progress() * 100)}% complete")

    fh.seek(0)
    with open(output_path, "wb") as f:
        f.write(fh.read())

    log_message(f"Downloaded: {output_path}")
    return output_path

def convert_ipynb_to_py(ipynb_path, output_folder):
    """Convert a Jupyter Notebook (.ipynb) file into a Python script (.py)."""
    os.makedirs(output_folder, exist_ok=True)
    py_filename = os.path.splitext(os.path.basename(ipynb_path))[0] + ".py"
    py_path = os.path.join(output_folder, py_filename)

    try:
        with open(ipynb_path, "r", encoding="utf-8") as f:
            notebook = eval(f.read())

        output_lines = [f"# Converted from {os.path.basename(ipynb_path)}\n"]
        for cell in notebook.get("cells", []):
            if cell.get("cell_type") == "markdown":
                markdown_text = "".join(cell["source"]).strip()
                output_lines.append("\n".join(f"# {line}" for line in markdown_text.split("\n")) + "\n")
            elif cell.get("cell_type") == "code":
                output_lines.append("".join(cell["source"]).strip() + "\n")

        with open(py_path, "w", encoding="utf-8") as py_file:
            py_file.write("\n".join(output_lines))

        log_message(f"Converted: {ipynb_path} -> {py_path}")
        return py_path
    except Exception as e:
        print(f"Error processing {ipynb_path}: {e}")
        return None
    return None

def main(csv_file, request):
    """Main function to download and convert notebooks."""
    creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    service = build("drive", "v3", credentials=creds)
    output_folder = f"./processor/download_container/{request.user.username}"


    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        if not header or "ColabLinks" not in header:
            print("CSV file is missing 'ColabLinks' column.")
            return

        colab_links_index = header.index("ColabLinks")

        for row in reader:
            if len(row) <= colab_links_index or not row[colab_links_index].strip():
                continue

            file_id = extract_file_id(row[colab_links_index])
            if file_id:
                try:
                    ipynb_path = download_colab_notebook(file_id, service, output_folder)
                    py_path = convert_ipynb_to_py(ipynb_path, output_folder)
                except Exception as e:
                    log_message(f"Error in download: {str(e)}")
                    raise


