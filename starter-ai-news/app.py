from flask import Flask, render_template, jsonify
import json
import os
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

# --- API KEYS & ENDPOINTS ---
GNEWS_API_KEY = "aeed94f6489b0667554329a561e387a8"  # Replace with your actual GNews key
GOOGLE_TRANSLATE_API_KEY = "AIzaSyCCG0_D1Pi8RQ7NcW9FV4-v3S8N85Kg4Jg"  # Replace with your actual Google API key
GNEWS_ENDPOINT = "https://gnews.io/api/v4/search"

CACHE_PATH = "data/news_cache.json"
LAST_FETCH_PATH = "data/last_fetch.json"

# --- TRANSLATION ---
def translate_to_french(text: str) -> str:
    if not text:
        return ""
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": "fr",
        "format": "text",
        "key": GOOGLE_TRANSLATE_API_KEY
    }

    try:
        response = requests.post(url, data=params)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
        else:
            print(f"Translation error {response.status_code}: {response.text}")
            return text  # fallback to English
    except requests.exceptions.RequestException as e:
        print(f"Translation exception: {e}")
        return text  # fallback to English


# --- CLASSIFICATION ---
def classify_article(title: str, summary: str) -> list:
    text = f"{title} {summary}".lower()
    categories = []
    if any(k in text for k in ["gpt-4o", "claude", "mistral", "llm", "transformer"]):
        categories.append("Model")
    if any(k in text for k in ["openai", "anthropic", "google deepmind", "meta", "microsoft", "amazon"]):
        categories.append("Company")
    if any(k in text for k in ["agent ai", "ai agent", "agentic ai"]):
        categories.append("Agent AI")
    return categories or ["General"]

# --- CACHE HANDLING ---
def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def should_fetch_fresh_news(interval_minutes=60):
    try:
        with open(LAST_FETCH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            last_time = datetime.fromisoformat(data["timestamp"])
            return datetime.now() - last_time > timedelta(minutes=interval_minutes)
    except:
        return True  # If file is missing or unreadable

def update_last_fetch_time():
    with open(LAST_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({ "timestamp": datetime.now().isoformat() }, f)

# --- FETCH NEWS ---
def fetch_ai_news():
    if not should_fetch_fresh_news():
        print("⏱ Using cached news (not time to fetch yet)")
        return load_cache()

    print("🌐 Fetching fresh news from GNews...")
    query = '("GPT-4o" OR "Claude" OR "Mistral" OR "Anthropic" OR "OpenAI" OR "Google DeepMind" OR "Agent AI")'
    params = {
        "q": query,
        "lang": "en",
        "max": 10,
        "apikey": GNEWS_API_KEY
    }

    response = requests.get(GNEWS_ENDPOINT, params=params)
    print(f"Querying GNews: {response.url}")
    if response.status_code != 200:
        print(f"GNews error: {response.status_code}")
        return load_cache()  # Fallback to previous cache

    articles = response.json().get("articles", [])
    cache = load_cache()
    updated = False
    final_stories = []

    for a in articles:
        title_en = a.get("title", "").strip()
        summary_en = a.get("description", "").strip()
        url = a.get("url")

        # Check if already cached
        cached = next((item for item in cache if item["url"] == url), None)

        if cached:
            final_stories.append(cached)
        else:
            title_fr = translate_to_french(title_en)
            summary_fr = translate_to_french(summary_en)

            story = {
                "timestamp": a.get("publishedAt"),
                "title": {"en": title_en, "fr": title_fr},
                "summary": {"en": summary_en, "fr": summary_fr},
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

# --- ROUTES ---
@app.route("/")
def home():
    news_items = load_cache()
    return render_template("index.html", news_items=news_items, language="en")

@app.route("/api/news")
def get_news():
    stories = fetch_ai_news()
    return jsonify(stories)

# --- MAIN ---
if __name__ == "__main__":
    app.run(debug=True)
