import pandas as pd
from sqlalchemy import create_engine
import urllib
import spacy
from tqdm import tqdm
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
import joblib
import re

# Setup
params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=SKYZEN\\HMI_PRO;"
    "DATABASE=HMI;"
    "Trusted_Connection=yes;"
)
engine = create_engine("mssql+pyodbc:///?odbc_connect=%s" % params)
tqdm.pandas()

# Load cleaned data
df = pd.read_sql("SELECT * FROM CleanedEmails", engine)

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

# --- Summarization (Simple Heuristic: First Sentence as Summary) ---
def simple_summary(text):
    doc = nlp(text)
    for sent in doc.sents:
        return sent.text
    return ""

df['summary'] = df['cleaned_body'].progress_apply(simple_summary)

# --- Classification (Rule-based for simplicity) ---
def classify(text):
    if "meeting" in text or "schedule" in text:
        return "Work"
    elif "invoice" in text or "payment" in text:
        return "Finance"
    elif "party" in text or "friend" in text:
        return "Personal"
    else:
        return "Other"

df['category'] = df['cleaned_body'].progress_apply(classify)

# --- Tagging (NER using spaCy) ---
def extract_tags(text):
    doc = nlp(text)
    entities = [ent.text for ent in doc.ents if ent.label_ in ["PERSON", "ORG", "GPE"]]
    return ", ".join(entities)

df['tags'] = df['cleaned_body'].progress_apply(extract_tags)

# --- Save to database ---
df[['id', 'summary', 'category', 'tags']].to_sql('AnalyzedEmails', con=engine, if_exists='replace', index=False)

print("Summarization, classification, and tagging completed and saved.")
