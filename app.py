import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
from fuzzywuzzy import fuzz

app = Flask(__name__)
load_dotenv()

# --- API Keys ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")

# --- File Paths ---
CACHE_PATH = "data/news_cache.json"
LAST_FETCH_PATH = "data/last_fetch.json"

# --- Translation ---
def translate_to_french(text: str) -> str:
    if not text:
        return ""
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": "fr",
        "format": "text",
        "key": GOOGLE_API_KEY
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        response = requests.post(url, data=params, headers=headers)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
        else:
            print(f"Translation error {response.status_code}: {response.text}")
            return text
    except requests.exceptions.RequestException as e:
        print(f"Translation exception: {e}")
        return text

# --- Classification ---
def classify_article(title: str, summary: str) -> list:
    text = f"{title} {summary}".lower()
    categories = []
    if any(k in text for k in ["gpt-5", "gpt-4o", "claude", "mistral", "llm", "transformer"]):
        categories.append("Model")
    if any(k in text for k in ["openai", "anthropic", "google deepmind", "meta", "microsoft", "amazon", "apple"]):
        categories.append("Company")
    if any(k in text for k in ["agent ai", "ai agent", "agentic ai"]):
        categories.append("Agent AI")
    return categories or ["General"]

# --- Cache Handling ---
def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def update_last_fetch_time():
    with open(LAST_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({ "timestamp": datetime.now().isoformat() }, f)

def should_fetch_fresh_news(interval_minutes=60):
    return True

# --- Deduplication (best-performing) ---
def deduplicate_by_token_set(articles, threshold=90):
    unique = []
    seen_texts = []

    for article in articles:
        title = article.get("title", "").strip()
        summary = article.get("description", "").strip()
        combined = f"{title} {summary}".lower()

        if not combined:
            continue

        if any(fuzz.token_set_ratio(combined, seen) >= threshold for seen in seen_texts):
            continue

        seen_texts.append(combined)
        unique.append(article)

    return unique

# --- GNews: Split queries ---
def fetch_gnews_articles():
    topics = ["OpenAI", "GPT-4o", "gpt-5", "Claude", "Anthropic", "Agent AI"]
    all_articles = []

    for topic in topics:
        params = {
            "q": f'"{topic}"',
            "lang": "en",
            "max": 3,  # limit per topic (GNews free tier = 10 max)
            "apikey": GNEWS_API_KEY
        }
        try:
            response = requests.get("https://gnews.io/api/v4/search", params=params)
            print(f"Querying GNews: {response.url}")
            if response.status_code == 200:
                all_articles.extend(response.json().get("articles", []))
            else:
                print(f"GNews error for {topic}: {response.status_code}")
        except Exception as e:
            print(f"GNews exception for {topic}: {e}")

    return all_articles

# --- NewsData.io integration ---
def fetch_newsdata_ai_news():
    query = "openai OR gpt-4o OR GPT-5 OR claude OR anthropic OR agent ai"
    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "q": query,
        "language": "en",
        "category": "technology",
        "country": "us",
        "page": 0
    }

    try:
        response = requests.get(url, params=params)
        print(f"Querying NewsData.io: {response.url}")
        if response.status_code != 200:
            print(f"NewsData error: {response.status_code}")
            return []

        articles = response.json().get("results", [])
        formatted = []
        for a in articles:
            formatted.append({
                "timestamp": a.get("pubDate"),
                "title": {
                    "en": a.get("title", ""),
                    "fr": translate_to_french(a.get("title", ""))
                },
                "summary": {
                    "en": a.get("description", ""),
                    "fr": translate_to_french(a.get("description", ""))
                },
                "url": a.get("link"),
                "categories": classify_article(a.get("title", ""), a.get("description", ""))
            })

        return formatted

    except Exception as e:
        print(f"NewsData fetch exception: {e}")
        return []

# --- Unified Fetch ---
def fetch_ai_news():
    if not should_fetch_fresh_news():
        print("⏱ Using cached news (not time to fetch yet)")
        return load_cache()

    print("🌐 Fetching fresh news from GNews and NewsData.io...")

    articles = fetch_gnews_articles()
    articles += fetch_newsdata_ai_news()

    print(f"🔍 Combined article pool size before deduping: {len(articles)}")
    articles = deduplicate_by_token_set(articles, threshold=90)
    print(f"✅ Deduplicated: {len(articles)} unique stories")

    cache = load_cache()
    updated = False
    final_stories = []

    for a in articles:
        title_en = a.get("title", "")
        summary_en = a.get("description", "")
        url = a.get("url")

        if not url:
            continue

        cached = next((item for item in cache if item["url"] == url), None)
        if cached:
            final_stories.append(cached)
        else:
            story = {
                "timestamp": a.get("timestamp", ""),
                "title": {"en": title_en, "fr": translate_to_french(title_en)},
                "summary": {"en": summary_en, "fr": translate_to_french(summary_en)},
                "url": url,
                "categories": classify_article(title_en, summary_en)
            }
            final_stories.append(story)
            cache.append(story)
            updated = True

    if updated:
        save_cache(cache)
        update_last_fetch_time()

    return final_stories

# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/news")
def get_news():
    stories = fetch_ai_news()
    return jsonify(stories)

# --- Main ---
if __name__ == "__main__":
    app.run(debug=True)
