import os
import re
import pyodbc
from datetime import datetime
from tqdm import tqdm
from dateutil import parser

# SQL Server connection
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=SKYZEN\\HMI_PRO;'
    'DATABASE=HMI;'
    'Trusted_Connection=yes;'
)
cursor = conn.cursor()

# Folder containing the .txt email files
DATA_FOLDER = './RawData'

# Field pattern mapping
FIELDS = [
    "Message-ID", "Date", "From", "To", "Subject", "Mime-Version",
    "Content-Type", "Content-Transfer-Encoding", "X-From", "X-To",
    "X-cc", "X-bcc", "X-Folder", "X-Origin", "X-FileName"
]

# Max length for NVARCHAR fields (same as your DB schema)
MAX_LENGTHS = {
    'from_email': 255,
    'x_from': 255,
    'x_folder': 255,
    'x_origin': 255,
    'x_filename': 255,
    # Add more if needed
}

def safe_trim(value, field_name):
    """Trims a string value to fit in DB column length."""
    if not value:
        return value
    max_len = MAX_LENGTHS.get(field_name)
    return value[:max_len] if max_len else value

def parse_email(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Split headers and body
        parts = content.split("\n\n", 1)
        headers = parts[0]
        body = parts[1] if len(parts) > 1 else ""

        email_data = {}
        for field in FIELDS:
            match = re.search(rf"^{field}:\s*(.*)", headers, re.MULTILINE)
            key = field.lower().replace("-", "_")
            email_data[key] = match.group(1).strip() if match else None

        email_data['body'] = body.strip()

        # Parse date safely
        raw_date = email_data.get('date')
        try:
            email_data['date'] = parser.parse(raw_date) if raw_date else None
        except Exception:
            email_data['date'] = None

        # Trim long fields
        email_data['from_email'] = safe_trim(email_data.get('from'), 'from_email')
        email_data['x_from'] = safe_trim(email_data.get('x_from'), 'x_from')
        email_data['x_folder'] = safe_trim(email_data.get('x_folder'), 'x_folder')
        email_data['x_origin'] = safe_trim(email_data.get('x_origin'), 'x_origin')
        email_data['x_filename'] = safe_trim(email_data.get('x_filename'), 'x_filename')

        if not email_data.get('message_id') and not email_data.get('from'):
            return None  # Skip files that are malformed

        return email_data

    except Exception as e:
        print(f"❌ Failed to parse {file_path}: {e}")
        return None

def insert_email(data):
    if not data:
        return

    cursor.execute("""
        INSERT INTO Emails (
            message_id, date, from_email, to_email, subject,
            mime_version, content_type, content_transfer_encoding,
            x_from, x_to, x_cc, x_bcc, x_folder, x_origin,
            x_filename, body
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get('message_id'),
        data.get('date'),
        data.get('from_email'),
        data.get('to'),
        data.get('subject'),
        data.get('mime_version'),
        data.get('content_type'),
        data.get('content_transfer_encoding'),
        data.get('x_from'),
        data.get('x_to'),
        data.get('x_cc'),
        data.get('x_bcc'),
        data.get('x_folder'),
        data.get('x_origin'),
        data.get('x_filename'),
        data.get('body')
    ))
    conn.commit()

def main():
    files = [os.path.join(DATA_FOLDER, f) for f in os.listdir(DATA_FOLDER) if f.endswith(".txt")]
    print(f"📁 Processing {len(files)} files...")

    for file_path in tqdm(files, desc="📤 Inserting emails"):
        try:
            data = parse_email(file_path)
            if data:
                insert_email(data)
            else:
                print(f"⚠️ Skipped: {file_path}")
        except Exception as e:
            print(f"❌ Error in file {file_path}: {e}")

    print("✅ All emails inserted successfully.")

if __name__ == "__main__":
    main()
