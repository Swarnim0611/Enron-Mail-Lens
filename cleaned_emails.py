import pandas as pd
from sqlalchemy import create_engine
import urllib
import nltk
import re
import spacy
import os
from nltk.corpus import stopwords
from nltk.tokenize import TreebankWordTokenizer
from tqdm import tqdm
tqdm.pandas()  # Enable progress_apply for pandas

# --- Database Connection ---
params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=SKYZEN\\HMI_PRO;"
    "DATABASE=HMI;"
    "Trusted_Connection=yes;"
)
engine = create_engine("mssql+pyodbc:///?odbc_connect=%s" % params)

# --- Load Data ---
df = pd.read_sql("SELECT * FROM Emails", engine)

# --- NLP Tools Setup ---
nltk.download('stopwords')
stop_words = set(stopwords.words('english'))

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    os.system('python -m spacy download en_core_web_sm')
    nlp = spacy.load("en_core_web_sm")

# --- Utility Functions ---
def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r'\d+', '', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    tokenizer = TreebankWordTokenizer()
    tokens = tokenizer.tokenize(text)
    tokens = [t for t in tokens if t not in stop_words]

    doc = nlp(" ".join(tokens))
    lemmatized = [token.lemma_ for token in doc]
    return " ".join(lemmatized)

def clean_generic_text(text):
    """Basic clean for metadata (no lemmatization or NLP)"""
    if not isinstance(text, str):
        return ""
    text = text.strip().lower()
    text = re.sub(r'[^\w\s@.-]', '', text)
    return text

# --- Clean Fields ---
df['body'] = df['body'].fillna('')
df['cleaned_body'] = df['body'].progress_apply(clean_text)

# Clean metadata fields
text_fields = [
    'from_email', 'to_email', 'subject', 'mime_version', 'content_type',
    'content_transfer_encoding', 'x_from', 'x_to', 'x_cc', 'x_bcc',
    'x_folder', 'x_origin', 'x_filename'
]

for field in text_fields:
    if field in df.columns:
        df[field] = df[field].fillna('')
        df[f'cleaned_{field}'] = df[field].progress_apply(clean_generic_text)

# Parse date/datetime
if 'date' in df.columns:
    df['parsed_date'] = pd.to_datetime(df['date'], errors='coerce')

# --- Optional Save (uncomment as needed) ---
# Save to new table in SQL Server
# df.to_sql("CleanedEmails", con=engine, if_exists='replace', index=False)

df_to_save = df[[
    'id', 'parsed_date', 'cleaned_body',
    'cleaned_from_email', 'cleaned_to_email', 'cleaned_subject',
    'cleaned_mime_version', 'cleaned_content_type', 'cleaned_content_transfer_encoding',
    'cleaned_x_from', 'cleaned_x_to', 'cleaned_x_cc', 'cleaned_x_bcc',
    'cleaned_x_folder', 'cleaned_x_origin', 'cleaned_x_filename'
]]

df_to_save.to_sql("CleanedEmails", con=engine, if_exists='replace', index=False)



# Save to Excel
# df.to_excel("cleaned_emails.xlsx", index=False)

# --- Display ---
#pd.set_option('display.max_columns', None)
##print(df.head())
