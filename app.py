from flask import Flask, render_template, request, session, redirect, url_for
from flask_caching import Cache
import pandas as pd
from gtts import gTTS
import hashlib
import matplotlib
import markdown
import nltk
from keybert import KeyBERT
from textblob import TextBlob
from collections import defaultdict

kw_model = KeyBERT()
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
# nltk.download('punkt')
# nltk.download('averaged_perceptron_tagger')
# nltk.download('wordnet')

# only download NLTK data if it isn’t already present
for pkg in ('punkt','averaged_perceptron_tagger','wordnet'):
    try:
        nltk.data.find(f'tokenizers/{pkg}')
    except LookupError:
        nltk.download(pkg, quiet=True)

matplotlib.use('Agg')
import os
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import networkx as nx
import plotly.graph_objects as go
from plotly.offline import plot
import plotly.express as px
from math import ceil
import json
import spacy

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering
from transformers import pipeline as hf_pipeline

_kw_model = None
_lda_model = None
_summarizer = None

app = Flask(__name__)
app.secret_key = 'Hmi@1234'

# configure a simple in-memory cache (for prod you’d swap to Redis, Memcached, etc.)
cache = Cache(config={
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': 3600   # 1 hour default
})
cache.init_app(app)

engine = create_engine(
    "mssql+pyodbc://SKYZEN\\HMI_PRO/HMI?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        # now pull back the plain-text password column
        query = text(
            "SELECT id, password FROM Users WHERE username = :username"
        )
        with engine.connect() as conn:
            row = conn.execute(query, {"username": username}).fetchone()

        if row:
            user_id, stored_password = row
            # direct compare, no hashing
            if password == stored_password:
                session['user_id'] = user_id
                return redirect(url_for('dashboard'))

        error = "Invalid credentials. Please try again."

    return render_template('login.html', error=error)


# ensure static folder exists
os.makedirs(os.path.join(app.root_path, 'static'), exist_ok=True)

vectorizer = CountVectorizer(stop_words='english', max_features=1000)
all_bodies = pd.read_sql(
    "SELECT cleaned_body FROM CleanedEmails WHERE cleaned_body IS NOT NULL",
    engine)['cleaned_body']
dtm = vectorizer.fit_transform(all_bodies.fillna(''))
lda_model = LatentDirichletAllocation(n_components=6, random_state=42)
lda_model.fit(dtm)

# # create a summarization pipeline once
# summarizer = pipeline(
#     "summarization",
#     model="facebook/bart-large-cnn",
#     tokenizer="facebook/bart-large-cnn",
#     framework="pt",
#     device=0  # or -1 if you don’t have a GPU
# )
# summarizer.tokenizer.model_max_length = 1024

# load the large summarization model only once, on CPU

summarizer = hf_pipeline(
    "summarization",
    model="facebook/bart-large-cnn",
    tokenizer="facebook/bart-large-cnn",
    framework="pt",
    device=-1
)
summarizer.tokenizer.model_max_length = 1024

# load emotion classifier a single time, too
emotion_classifier = hf_pipeline(
    "text-classification",
    model="j-hartmann/emotion-english-distilroberta-base",
    top_k=1,
    device=-1
)


# near the top, after cache.init_app(app):
@cache.memoize(timeout=3600)
def load_emails():
    """Load core Emails table once per hour."""
    df = pd.read_sql(
        "SELECT id, message_id, date, from_email, to_email, subject, body FROM Emails",
        engine,
        parse_dates=['date']
    )
    # drop bad dates and add day/hour columns
    df.dropna(subset=['date'], inplace=True)
    df['day'] = df['date'].dt.day_name()
    df['hour'] = df['date'].dt.hour
    return df

@cache.memoize(timeout=3600)
def load_cleaned_emails():
    """Load cleaned emails for prompt-based searches."""
    cdf = pd.read_sql(
        "SELECT id, cleaned_subject AS subject, cleaned_body, "
        "cleaned_from_email AS from_email, cleaned_to_email AS to_email, parsed_date AS date "
        "FROM CleanedEmails WHERE cleaned_body IS NOT NULL",
        engine,
        parse_dates=['date']
    )
    cdf.dropna(subset=['date'], inplace=True)
    return cdf


@cache.memoize(timeout=3600)
def load_analyzed_stories():
    """
    Load and cache the AnalyzedEmails table as a list of dicts,
    ready to render in the dashboard.
    """
    df = pd.read_sql(
        "SELECT summary, category, tags FROM AnalyzedEmails WHERE summary IS NOT NULL",
        engine
    )
    stories = []
    for _, row in df.iterrows():
        actors = [t.strip() for t in (row.tags or "").split(",") if t.strip()]
        stories.append({
            "title":    row.summary.split(".")[0].capitalize(),
            "summary":  row.summary,
            "category": row.category,
            "actors":   actors,
            "tags":     row.tags or ""
        })
    return stories




@app.route('/')
@cache.cached(timeout=300, query_string=True)
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    active_tab = request.args.get("tab", "overview")
    search_query = request.args.get("search_query", "").strip()
    search_results = []

    # with engine.connect() as conn:
    #     result = conn.execute(
    #         text("SELECT summary, category, tags FROM AnalyzedEmails")
    #     ).fetchall()
    # result = load_analyzed_emails()

    # final_stories = [
    #         {
    #             "title":
    #             row.summary.split('.')[0].capitalize(),
    #             "summary":
    #             row.summary,
    #             "category":
    #             row.category,
    #             "actors":
    #             [tag.strip() for tag in row.tags.split(',')
    #              if tag.strip()] if row.tags else [],
    #             "tags":
    #             row.tags if row.tags else ""  # Ensures 'tags' always exists
    #         } for row in result if row.summary
    # ]

    final_stories = load_analyzed_stories()


    # --- Load and prepare data ---
    # df = pd.read_sql(
    #     "SELECT id, message_id, date, from_email, to_email, subject FROM Emails",
    #     engine)

    df = load_emails()

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df.dropna(subset=['date'], inplace=True)
    df['day'] = df['date'].dt.day_name()
    df['hour'] = df['date'].dt.hour

    prompt = request.args.get("prompt", "").strip()
    prompt_stories = []  # ✅ Default initialization to avoid UnboundLocalError
    narrative_story = "No prompt was entered or no matching emails found."  # Default fallback
    # Always initialize these, so even if prompt is empty

    #thread_stories = []
    topic_stories = []

    # Load cleaned content for deeper prompt-based search
    # cleaned_df = pd.read_sql(
    #     "SELECT id, cleaned_subject as subject, cleaned_body, cleaned_from_email as from_email, cleaned_to_email as to_email, parsed_date as date FROM CleanedEmails",
    #     engine)

    cleaned_df = load_cleaned_emails()

    cleaned_df['date'] = pd.to_datetime(cleaned_df['date'], errors='coerce')
    cleaned_df.dropna(subset=['date'], inplace=True)

    #filtered_df = pd.DataFrame()
    filtered_df = pd.DataFrame(columns=[
        "from_email", "to_email", "subject", "date", "hour", "day",
        "cleaned_body"
    ])

    if prompt:
        print(f"🔎 Prompt search: {prompt}")
        mask = (
            cleaned_df['subject'].str.contains(prompt, case=False, na=False) |
            cleaned_df['from_email'].str.contains(prompt, case=False, na=False)
            | cleaned_df['to_email'].str.contains(prompt, case=False, na=False)
            | cleaned_df['cleaned_body'].str.contains(
                prompt, case=False, na=False))

        filtered_df = cleaned_df[mask].copy()
        filtered_df['hour'] = filtered_df['date'].dt.hour
        filtered_df['day'] = filtered_df['date'].dt.day_name()
        prompt_stories = generate_prompt_stories(filtered_df)
        #thread_stories = generate_threaded_stories(filtered_df, max_stories=6)
        topic_stories = generate_topic_stories(filtered_df)

    if not filtered_df.empty:
        first_date = filtered_df['date'].min().strftime('%B %d, %Y')
        last_date = filtered_df['date'].max().strftime('%B %d, %Y')

        introduction = (
            f"Between {first_date} and {last_date}, emails referencing '{prompt}' "
            "reveal a series of activities involving key individuals.")

        top_senders = filtered_df['from_email'].value_counts().head(5)
        actor_lines = []
        for sender, count in top_senders.items():
            name = sender.split('@')[0].replace('.', ' ').title()
            actor_lines.append(f"- {name} ({sender}) sent {count} emails")

        late_night = filtered_df[filtered_df['hour'].between(0, 5)].shape[0]
        weekend = filtered_df[filtered_df['day'].isin(['Saturday',
                                                       'Sunday'])].shape[0]

        insight = (
            f"{late_night} late-night and {weekend} weekend emails suggest urgency. "
            "The emails show strategic communication across departments.")

        key_section = '\n'.join(actor_lines)
        #timeline = '\n'.join(quote_lines)
        insights = insight
        significance = "This section interprets the broader impact of the email activity."

        narrative_story = f"""
### Introduction
{introduction}

### Key Individuals
{key_section}

### Strategic Insights
{insights}

### Why It Matters
{significance}

This reveals internal dynamics and key decision-making under pressure regarding "{prompt}".
"""

    else:
        narrative_story = f"No story found for prompt: '{prompt}'"
        prompt_network_html = "<p>No network graph generated due to lack of data.</p>"

    prompt_network_html = build_prompt_graph(filtered_df)
    narrative_html = markdown.markdown(narrative_story)

    # 🧠 Extract sentiment-based sample quotes from prompt-filtered emails
    sample_quotes = []
    narrative_sentiment = 'Neutral'

    # 1. Detect sentiment of overall story
    narrative_score = TextBlob(narrative_story).sentiment.polarity
    if narrative_score > 0.2:
        narrative_sentiment = 'Positive'
    elif narrative_score < -0.2:
        narrative_sentiment = 'Negative'

    # 2. Pull 3–5 matching quotes from email subjects
    for _, row in filtered_df.iterrows():
        if 'subject' in row and isinstance(row['subject'], str):
            sentence = row['subject'].strip()
            sentiment = TextBlob(sentence).sentiment.polarity
        if (narrative_sentiment == 'Positive' and sentiment > 0.2) or \
           (narrative_sentiment == 'Negative' and sentiment < -0.2) or \
           (narrative_sentiment == 'Neutral' and -0.2 <= sentiment <= 0.2):
            sample_quotes.append(sentence[:300])
        if len(sample_quotes) >= 5:
            break

    # --- Extract email domains from 'to_email' ---
    def extract_domain(email):
        if pd.isna(email):
            return "Unknown"
        email = email.split(',')[0].strip()  # handle multiple recipients
        return email.split('@')[-1].lower() if '@' in email else "Invalid"

    df['to_domain'] = df['to_email'].apply(extract_domain)

    # sentiment_df = pd.read_sql(
    #     "SELECT cleaned_subject as subject, cleaned_body as body FROM CleanedEmails WHERE cleaned_body IS NOT NULL",
    #     engine)

    sentiment_df = load_cleaned_emails()

    sentiment_df.dropna(subset=['cleaned_body'], inplace=True)

    def analyze_sentiment(text):
        blob = TextBlob(text)
        return blob.sentiment.polarity  # Range: -1 (negative) to 1 (positive)

    sentiment_df['sentiment_score'] = sentiment_df['cleaned_body'].apply(
        analyze_sentiment)
    sentiment_df['sentiment_label'] = sentiment_df['sentiment_score'].apply(
        lambda x: 'Positive' if x > 0.1 else ('Negative'
                                              if x < -0.1 else 'Neutral'))

    sentiment_counts = sentiment_df['sentiment_label'].value_counts(
    ).reset_index()
    sentiment_counts.columns = ['Sentiment', 'Count']

    fig_sentiment = px.pie(
        sentiment_counts,
        names='Sentiment',
        values='Count',
        title='Overall Email Sentiment',
        color_discrete_sequence=['#2ca02c', '#ff7f0e', '#1f77b4'])

    sentiment_chart_html = fig_sentiment.to_html(full_html=False)

    # --- Metrics ---
    total_emails = len(df)
    unique_senders = df['from_email'].nunique()
    date_min = df['date'].min().date()
    date_max = df['date'].max().date()

    # --- Line Chart ---
    monthly_volume = df.groupby(
        df['date'].dt.to_period('M')).size().reset_index(name='count')
    monthly_volume['date'] = monthly_volume['date'].astype(str)
    fig = px.line(monthly_volume,
                  x='date',
                  y='count',
                  markers=True,
                  title='Email Volume Over Time')

    fig.update_layout(height=400,
                      margin=dict(t=60, b=60, l=50, r=30),
                      title_font_size=18,
                      xaxis_title_font=dict(size=14),
                      yaxis_title_font=dict(size=14),
                      font=dict(size=12))
    chart_html = fig.to_html(full_html=False)

    top_senders = df['from_email'].value_counts().head(10).reset_index()
    filtered_df = df[df['from_email'].isin(top_senders)]

    cytoscape_elements = build_sigma_elements(filtered_df)

    top_senders.columns = ['from_email', 'email_count']

    fig_top_senders = px.bar(top_senders,
                             x='email_count',
                             y='from_email',
                             orientation='h',
                             title='Top 10 Senders',
                             color_discrete_sequence=['#2a3a7c'])
    top_senders = top_senders.sort_values('email_count', ascending=True)
    fig_top_senders.update_layout(template="plotly_white",
                                  height=400,
                                  margin=dict(l=20, r=20, t=50, b=20))
    top_senders_html = fig_top_senders.to_html(full_html=False)

    heatmap_data = df.groupby(['day', 'hour']).size().reset_index(name='count')
    heatmap_data['day'] = pd.Categorical(heatmap_data['day'],
                                         categories=[
                                             "Monday", "Tuesday", "Wednesday",
                                             "Thursday", "Friday", "Saturday",
                                             "Sunday"
                                         ],
                                         ordered=True)

    fig_heatmap = px.density_heatmap(heatmap_data,
                                     x='hour',
                                     y='day',
                                     z='count',
                                     histfunc='sum',
                                     nbinsx=24,
                                     color_continuous_scale='Blues',
                                     title='Email Activity by Hour and Day')
    #fig_heatmap.update_layout(height=400, margin=dict(t=20, l=20, r=20, b=20))
    fig_heatmap.update_layout(height=500,
                              margin=dict(t=80, b=60, l=80, r=80),
                              title_font_size=18,
                              font=dict(size=13),
                              xaxis=dict(title="Hour of Day"),
                              yaxis=dict(title="Day of Week"))
    heatmap_img_html = fig_heatmap.to_html(full_html=False)

    # --- Pie Chart: Internal vs External Domains ---
    domain_counts = df['to_domain'].value_counts().reset_index()
    domain_counts.columns = ['Domain', 'Email Count']
    domain_counts['Type'] = domain_counts['Domain'].apply(
        lambda x: 'Internal' if 'enron.com' in x else 'External')

    # --- Bar Chart: Top External Domains ---
    top_external = domain_counts[domain_counts['Type'] == 'External'].head(10)

    fig_top_external = px.bar(top_external,
                              x='Email Count',
                              y='Domain',
                              orientation='h',
                              title='Top 10 External Domains',
                              color_discrete_sequence=['#2a3a7c'])
    fig_top_external.update_layout(template="plotly_white",
                                   height=400,
                                   margin=dict(l=20, r=20, t=50, b=20))
    top_external_domains_html = fig_top_external.to_html(full_html=False)

    pie_data = domain_counts.groupby('Type')['Email Count'].sum().reset_index()

    fig_domains = px.pie(pie_data,
                         values='Email Count',
                         names='Type',
                         title='Internal vs External Emails',
                         color_discrete_sequence=['#1a2a6c', '#6c8cff'])

    fig_domains.update_layout(template="plotly_white",
                              height=400,
                              margin=dict(l=20, r=20, t=50, b=20))
    internal_external_pie_html = fig_domains.to_html(full_html=False)

    # --- Bar Chart: Top 10 Email Subjects (Threads) ---
    thread_counts = df['subject'].value_counts().reset_index()
    thread_counts.columns = ['Subject', 'Count']
    top_threads = thread_counts.head(10)

    fig_threads = px.bar(top_threads,
                         x='Count',
                         y='Subject',
                         orientation='h',
                         title='Top 10 Email Threads (by Subject)',
                         color_discrete_sequence=['#1a2a6c'])
    fig_threads.update_layout(template="plotly_white",
                              height=400,
                              margin=dict(l=20, r=20, t=50, b=20))
    top_threads_html = fig_threads.to_html(full_html=False)

    # --- Late Night Emails (12 AM to 5 AM) ---
    late_night_df = df[df['hour'].between(0, 5)]

    # Chart: Email counts by hour (0 to 5)
    late_hour_counts = late_night_df['hour'].value_counts().sort_index(
    ).reset_index()
    late_hour_counts.columns = ['Hour', 'Count']
    fig_late_hours = px.bar(late_hour_counts,
                            x='Hour',
                            y='Count',
                            title='Late Night Email Activity (12 AM – 5 AM)',
                            color_discrete_sequence=['#2a3a7c'])
    fig_late_hours.update_layout(template="plotly_white",
                                 height=400,
                                 margin=dict(l=20, r=20, t=50, b=20))
    late_hour_chart_html = fig_late_hours.to_html(full_html=False)

    # Chart: Top senders during late hours
    top_late_senders = late_night_df['from_email'].value_counts().head(
        10).reset_index()
    top_late_senders.columns = ['Sender', 'Count']
    fig_late_senders = px.bar(top_late_senders,
                              x='Count',
                              y='Sender',
                              orientation='h',
                              title='Top Senders (12 AM – 5 AM)',
                              color_discrete_sequence=['#1a2a6c'])
    fig_late_senders.update_layout(template="plotly_white",
                                   height=400,
                                   margin=dict(l=20, r=20, t=50, b=20))
    late_sender_chart_html = fig_late_senders.to_html(full_html=False)

    # --- Topic Modeling via LDA (on Subjects) ---
    # clean_df = pd.read_sql(
    #     "SELECT cleaned_subject FROM CleanedEmails WHERE cleaned_subject IS NOT NULL",
    #     engine)

    clean_df = load_cleaned_emails()
    subjects = clean_df['subject'].dropna().tolist()
    lda_html = ""
    try:
        vectorizer = CountVectorizer(stop_words='english')
        doc_term = vectorizer.fit_transform(subjects)
        lda = LatentDirichletAllocation(n_components=5)
        lda.fit(doc_term)
        words = vectorizer.get_feature_names_out()
        for idx, topic in enumerate(lda.components_):
            top_words = [words[i] for i in topic.argsort()[-6:][::-1]]
            lda_html += f"<h5>📚 Topic {idx + 1}</h5><p>{' | '.join(top_words)}</p>"
    except:
        lda_html = "<p>No topic data available.</p>"

    # Step 1: Prepare sender → receiver data for network graph
    edges_df = df[['from_email', 'to_email']].dropna()
    edges_df['to_email'] = edges_df['to_email'].apply(
        lambda x: x.split(',')[0].strip())  # First recipient only
    edges_df = edges_df.groupby(['from_email',
                                 'to_email']).size().reset_index(name='weight')

    # Build the directed graph
    G = nx.DiGraph()
    for index, row in edges_df.iterrows():
        G.add_edge(row['from_email'], row['to_email'], weight=row['weight'])

    # Select top 50 edges for visibility
    top_edges = sorted(G.edges(data=True),
                       key=lambda x: x[2]['weight'],
                       reverse=True)[:50]
    H = nx.DiGraph()
    for u, v, d in top_edges:
        H.add_edge(u, v, weight=d['weight'])

    # Get positions for nodes
    pos = nx.spring_layout(H, k=0.5, iterations=50)

    # Prepare Plotly data
    edge_x = []
    edge_y = []

    for edge in H.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    node_x = []
    node_y = []
    node_text = []

    for node in H.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)

    edge_trace = go.Scatter(x=edge_x,
                            y=edge_y,
                            line=dict(width=1, color='#888'),
                            hoverinfo='none',
                            mode='lines')

    node_trace = go.Scatter(x=node_x,
                            y=node_y,
                            mode='markers+text',
                            textposition='top center',
                            hoverinfo='text',
                            text=node_text,
                            marker=dict(showscale=False,
                                        color='#1a2a6c',
                                        size=10,
                                        line_width=2))

    fig_network = go.Figure(data=[edge_trace, node_trace],
                            layout=go.Layout(title=dict(
                                text='Email Communication Network',
                                font=dict(size=16)),
                                             showlegend=False,
                                             margin=dict(t=40),
                                             hovermode='closest'))

    network_graph_html = fig_network.to_html(full_html=False)

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT TOP 10 from_email, COUNT(*) as count 
                FROM Emails 
                GROUP BY from_email 
                ORDER BY count DESC
        """))


        top_senders = result.fetchall()

    senders = [row[0] for row in top_senders]
    counts = [row[1] for row in top_senders]

    bar_chart = go.Figure(data=[go.Bar(x=senders, y=counts)],
                          layout=go.Layout(title=dict(
                              text="Top 10 Most Active Senders",
                              font=dict(size=18)),
                                           xaxis=dict(title='Sender'),
                                           yaxis=dict(title='Email Count')))
    sender_bar_div = plot(bar_chart, output_type='div')

    # Get filter params from request
    selected_sender = request.args.get('sender', 'All')
    selected_month = request.args.get('month', 'All')

    story_df = df.copy()
    if selected_sender != 'All':
        story_df = story_df[story_df['from_email'] == selected_sender]
    # if selected_month != 'All':
    #     story_df = story_df[story_df['date'].dt.strftime('%B %Y') == selected_month]
    if selected_month != 'All':
        story_df = story_df[story_df['date'].dt.strftime('%B %Y') ==
                            selected_month]

    # Debugging log
    print("Filtered DF Shape:", story_df.shape)

    engagement_stats = {}

    peak_month = "N/A"
    peak_count = 0
    avg_daily_volume = 0
    top_sender = ""
    top_sender_count = 0
    top_recipient = ""
    top_recipient_count = 0
    most_active_subject = "N/A"
    most_active_count = 0

    if not story_df.empty:
        monthly_counts = story_df.groupby(
            story_df['date'].dt.to_period("M")).size()
        peak_month = str(monthly_counts.idxmax())
        peak_count = monthly_counts.max()
        avg_daily_volume = round(
            story_df.groupby(story_df['date'].dt.date).size().mean(), 1)

    engagement_stats = {
        "peak_month": peak_month,
        "peak_count": peak_count,
        "avg_daily": avg_daily_volume
    }

    story_timeline = story_df.sort_values('date')[[
        'date', 'from_email', 'to_email', 'subject'
    ]].to_dict(orient='records')

    # Sender and month filter values
    all_senders = sorted(df['from_email'].dropna().unique().tolist())
    all_months = sorted(df['date'].dt.strftime('%B %Y').unique().tolist())

    trend_data = story_df.groupby(
        story_df['date'].dt.date).size().reset_index(name='count')
    fig = px.line(trend_data,
                  x='date',
                  y='count',
                  title='Engagement Over Time')
    story_chart_html = fig.to_html(full_html=False)

    if not story_df.empty:
        top_sender = story_df['from_email'].value_counts().idxmax()
        top_sender_count = story_df['from_email'].value_counts().max()

        top_recipient = story_df['to_email'].dropna().apply(
            lambda x: x.split(',')[0]).value_counts().idxmax()
        top_recipient_count = story_df['to_email'].dropna().apply(
            lambda x: x.split(',')[0]).value_counts().max()
    else:
        top_sender = top_sender_count = top_recipient = top_recipient_count = None

    late_night_count = story_df[story_df['hour'].between(0, 5)].shape[0]
    weekend_count = story_df[story_df['day'].isin(['Saturday',
                                                   'Sunday'])].shape[0]

    if not story_df.empty:
        top_thread_series = story_df['subject'].value_counts().head(1)
        most_active_subject = top_thread_series.index[0]
        most_active_count = top_thread_series.iloc[0]
    else:
        most_active_subject = "N/A"
        most_active_count = 0

    # Pagination parameters
    page = int(request.args.get("page", 1))
    per_page = 10  # emails per page

    # Total pages
    total_pages = ceil(len(story_timeline) / per_page)

    # Slice the timeline for the current page
    start = (page - 1) * per_page
    end = start + per_page
    story_timeline_paginated = story_timeline[start:end]

    # Email activity summary for Overview
    daily_counts = df.groupby('date').size()
    peak_day = daily_counts.idxmax()
    peak_count = daily_counts.max()
    avg_per_day = round(daily_counts.mean(), 2)

    top_sender = df['from_email'].value_counts().idxmax()
    top_sender_count = df['from_email'].value_counts().max()

    daily_counts = df.groupby('date').size().reset_index(name='count')
    fig_daily = px.line(daily_counts,
                        x='date',
                        y='count',
                        title="Daily Email Volume Trend")
    #fig_daily.update_layout(height=200, margin=dict(t=20, b=20), showlegend=False)
    fig_daily.update_layout(title="📈 Daily Email Volume Trend",
                            title_font_size=20,
                            margin=dict(t=70, b=60))
    volume_chart_base64 = fig_daily.to_html(full_html=False)

    cytoscape_data = json.dumps(cytoscape_elements).replace(
        "</", "<\\/")  # Prevent script breaks

    # new Podcast section
    podcast_query = request.args.get('podcast_query', '').strip()
    podcast_script = None
    podcast_file_url = None

    if request.args.get('tab') == 'podcast' and podcast_query:
        # 1) fetch top 5 bodies
        df_raw = pd.read_sql(
            text("SELECT TOP 5 body FROM Emails WHERE body LIKE :q"),
            engine,
            params={'q': f'%{podcast_query}%'})
        joined = ' '.join(df_raw['body'].dropna().tolist())
        # 2) summarize
        podcast_script = summarize_text(joined,
                                        n_sentences=4) or "No content found."
        # 3) generate TTS
        tts = gTTS(podcast_script)
        mp3_path = os.path.join(app.root_path, 'static', 'podcast.mp3')
        tts.save(mp3_path)
        podcast_file_url = url_for('static', filename='podcast.mp3')

    # --- Render Template ---
    return render_template(
        'dashboard.html',
        total_emails=total_emails,
        unique_senders=unique_senders,
        date_range=f"{date_min} to {date_max}",
        peak_day=peak_day,
        peak_count=peak_count,
        avg_per_day=avg_per_day,
        volume_chart_base64=volume_chart_base64,
        chart_html=chart_html,
        top_senders_html=top_senders_html,
        heatmap_img_html=heatmap_img_html,
        internal_external_pie_html=internal_external_pie_html,
        top_external_domains_html=top_external_domains_html,
        top_threads_html=top_threads_html,
        late_hour_chart_html=late_hour_chart_html,
        late_sender_chart_html=late_sender_chart_html,
        lda_html=lda_html,
        network_graph_html=network_graph_html,
        sender_bar_div=sender_bar_div,
        all_senders=all_senders,
        all_months=all_months,
        engagement_stats=engagement_stats,
        active_tab=active_tab,
        story_chart_html=story_chart_html,
        top_sender=top_sender,
        top_sender_count=top_sender_count,
        top_recipient=top_recipient,
        top_recipient_count=top_recipient_count,
        late_night_count=late_night_count,
        weekend_count=weekend_count,
        most_active_subject=most_active_subject,
        most_active_count=most_active_count,
        story_timeline=story_timeline_paginated,
        page=page,
        total_pages=total_pages,
        cytoscape_data=cytoscape_data,
        search_query=search_query,
        search_results=search_results,
        final_stories=final_stories,
        prompt=prompt,
        narrative_story=narrative_story,
        narrative_html=narrative_html,
        prompt_network_html=prompt_network_html,
        sentiment_chart_html=sentiment_chart_html,
        sentiment_quotes=sample_quotes,
        narrative_sentiment=narrative_sentiment,
        prompt_stories=prompt_stories,
        topic_stories=topic_stories,
        podcast_query=podcast_query,
        podcast_script=podcast_script,
        podcast_file_url=podcast_file_url)


def build_sigma_elements(df):
    nodes = set(df['from_email'].dropna()).union(df['to_email'].dropna())
    node_elements = [{
        'data': {
            'id': node,
            'label': node.split('@')[0] if isinstance(node, str) else str(node)
        }
    } for node in nodes if node]

    edges = df[['from_email', 'to_email']].dropna()
    edge_elements = [{
        'data': {
            'source': row['from_email'],
            'target': row['to_email']
        }
    } for _, row in edges.iterrows()]

    return node_elements + edge_elements


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


def build_prompt_graph(df_filtered):
    if df_filtered.empty or 'from_email' not in df_filtered.columns or 'to_email' not in df_filtered.columns:
        return "<p>No network graph generated due to lack of data.</p>"
    import networkx as nx
    import plotly.graph_objects as go

    edges_df = df_filtered[['from_email', 'to_email']].dropna()
    edges_df['to_email'] = edges_df['to_email'].apply(
        lambda x: x.split(',')[0].strip())
    edge_weights = edges_df.groupby(['from_email', 'to_email'
                                     ]).size().reset_index(name='weight')

    G = nx.DiGraph()
    for _, row in edge_weights.iterrows():
        G.add_edge(row['from_email'], row['to_email'], weight=row['weight'])

    # Keep only top 30 edges to avoid clutter
    top_edges = sorted(G.edges(data=True),
                       key=lambda x: x[2]['weight'],
                       reverse=True)[:30]
    H = nx.DiGraph()
    for u, v, d in top_edges:
        H.add_edge(u, v, weight=d['weight'])

    pos = nx.spring_layout(H, k=0.5, iterations=50)

    edge_x, edge_y, node_x, node_y, node_text = [], [], [], [], []

    for u, v in H.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    for node in H.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)

    edge_trace = go.Scatter(x=edge_x,
                            y=edge_y,
                            line=dict(width=1, color='#888'),
                            hoverinfo='none',
                            mode='lines')

    node_trace = go.Scatter(x=node_x,
                            y=node_y,
                            mode='markers+text',
                            textposition='top center',
                            text=node_text,
                            hoverinfo='text',
                            marker=dict(color='#1a2a6c', size=10,
                                        line_width=2))

    fig = go.Figure(data=[edge_trace, node_trace],
                    layout=go.Layout(title="",
                                     margin=dict(t=40),
                                     hovermode='closest'))

    return fig.to_html(full_html=False)




def generate_prompt_stories(df, max_stories=5):

    # # Emotion classifier (six basic emotions)
    # emotion_classifier = pipeline(
    #     "text-classification",
    #     model="j-hartmann/emotion-english-distilroberta-base",
    #     return_all_scores=False)



    stories = []
    grouped = df.groupby(['from_email', 'to_email'])

    for (sender, receiver), group in grouped:
        if group.empty or len(stories) >= max_stories:
            continue

        # 1) Date range
        dates = group['date'].dropna().astype(str).tolist()
        if dates:
            start_date = min(dates)[:10]
            end_date = max(dates)[:10]
            date_range = f"{start_date} to {end_date}"
        else:
            date_range = "Unknown period"

        # 2) Combine and summarize text
        combined_text = ' '.join(
            group['cleaned_body'].dropna().astype(str).tolist())[:1000]
        blob = TextBlob(combined_text)
        summary_sentences = blob.sentences[:2]
        summary_text = ' '.join(str(s) for s in summary_sentences)
        sentiment_score = round(blob.sentiment.polarity, 2)

        # 3) Extract keywords
        keywords = kw_model.extract_keywords(combined_text,
                                             keyphrase_ngram_range=(1, 2),
                                             stop_words='english',
                                             top_n=5)
        keyword_list = [kw[0] for kw in keywords]

        # 4) Determine tone
        try:
            emo = emotion_classifier(summary_text)[0]['label']
        except Exception:
            emo = "neutral"

        lowered = combined_text.lower()

        # domain-friendly overrides
        SECURITY_KEYWORDS = {
            'verify', 'password', 'account', 'bank', 'encrypted'
        }
        ACTION_KEYWORDS = {'urgent', 'wire', 'transfer', 'click'}
        INVOICE_KEYWORDS = {'invoice'}

        if any(k in lowered for k in SECURITY_KEYWORDS):
            tone = "Verification Required"
        elif any(k in lowered for k in INVOICE_KEYWORDS):
            tone = "Invoice"
        elif any(k in lowered for k in ACTION_KEYWORDS):
            tone = "Action Needed"
        else:
            tone = emo

        # 5) Build story dict
        title = f"Communication between {sender.split('@')[0]} and {receiver.split('@')[0]}"
        stories.append({
            "title":
            title,
            "actors":
            f"{sender}, {receiver}",
            "summary":
            (f"Between {date_range}, {sender} emailed {receiver}. "
             f"Summary: {summary_text} (Sentiment: {sentiment_score})"),
            "tags":
            ', '.join(keyword_list),
            "tone":
            tone
        })

    return stories



def generate_topic_stories(df, n_top_words=4):
    """
    For each LDA topic, find emails in df whose body contains
    any of the topic’s top words, then build a short + full story.
    """
    stories = []
    feature_names = vectorizer.get_feature_names_out()

    for topic_idx, comp in enumerate(lda_model.components_):
        # 1) pick top words
        top_idxs = comp.argsort()[-n_top_words:][::-1]
        top_words = [feature_names[i] for i in top_idxs]
        pattern = '|'.join(top_words)

        subset = df[df['cleaned_body'].str.contains(pattern, case=False, na=False)]
        if subset.empty:
            continue

        # title
        title = f"{', '.join(top_words)}"

        # actors
        all_em = pd.concat([subset['from_email'], subset['to_email']])
        top5 = all_em.value_counts().head(5).index.tolist()
        if all_em.nunique() > 5:
            top5.append(f"... +{all_em.nunique()-5} more")
        actors = ', '.join(top5)

        # combine text
        text = ' '.join(subset['cleaned_body'].dropna().tolist())[:1500]
        blob = TextBlob(text)
        sentences = blob.sentences

        # build short (1 sent) + full (up to 3)
        if len(sentences) >= 1:
            short = str(sentences[0])
            full  = ' '.join(str(s) for s in sentences[:3])
        else:
            short = full = text[:200]

        stories.append({
            "title": title,
            "actors": actors,
            "short_summary": short,
            "full_summary": full,
            "summary":       full
        })

    return stories




def summarize_text(text, n_sentences=4):
    """
    Summarize up to the first ~1024 tokens.  If that fails, fall back to
    chunking down the text into ~800-token pieces.
    """
    # target summary lengths (you can tweak these ratios)
    max_len = n_sentences * 40
    min_len = n_sentences * 20

    # try the whole text (pipeline will truncate to 1024 tokens by default)
    try:
        out = summarizer(text,
                         max_length=max_len,
                         min_length=min_len,
                         truncation=True)
        return out[0]["summary_text"]
    except Exception:
        # if it still barfs, split & summarize in chunks
        return chunk_and_summarize(text, max_len, min_len)


def chunk_and_summarize(text,
                        max_len,
                        min_len,
                        chunk_chars=2000,
                        overlap_chars=500):
    # split into sentences
    sentences = nltk.sent_tokenize(text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) > chunk_chars:
            chunks.append(current)
            # carry an overlap window forward
            current = current[-overlap_chars:]
        current += " " + sent
    if current:
        chunks.append(current)

    # summarize each chunk
    partials = []
    for c in chunks:
        try:
            part = summarizer(c,
                              max_length=max_len,
                              min_length=min_len,
                              truncation=True)[0]["summary_text"]
        except Exception:
            # as a last ditch, just take the first 200 chars
            part = c[:200]
        partials.append(part)

    # optional second-stage refine
    full = " ".join(partials)
    try:
        return summarizer(full,
                          max_length=max_len,
                          min_length=min_len,
                          truncation=True)[0]["summary_text"]
    except Exception:
        return full


def get_kw_model():
    global _kw_model
    if _kw_model is None:
        _kw_model = KeyBERT()
    return _kw_model

def get_lda_model():
    global _lda_model
    if _lda_model is None:
        # load your vectorizer+LDA here
        vec = CountVectorizer(stop_words='english', max_features=1000)
        bodies = pd.read_sql("...", engine)['cleaned_body'].fillna('')
        dtm = vec.fit_transform(bodies)
        model = LatentDirichletAllocation(n_components=6, random_state=42)
        model.fit(dtm)
        _lda_model = (vec, model)
    return _lda_model

def get_summarizer():
    global _summarizer
    if _summarizer is None:
        pipe = pipeline("summarization", model="facebook/bart-large-cnn", tokenizer="facebook/bart-large-cnn", framework="pt", device=0)
        pipe.tokenizer.model_max_length = 1024
        _summarizer = pipe
    return _summarizer


if __name__ == '__main__':
    app.run(debug=True, threaded=True)
