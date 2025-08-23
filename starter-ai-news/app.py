import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv

app = Flask(__name__)

# --- Load Environment Variables ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

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
    if any(k in text for k in ["gpt-4o", "claude", "mistral", "llm", "transformer"]):
        categories.append("Model")
    if any(k in text for k in ["openai", "anthropic", "google deepmind", "meta", "microsoft", "amazon"]):
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

def should_fetch_fresh_news(interval_minutes=60):
    return True

def update_last_fetch_time():
    with open(LAST_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({ "timestamp": datetime.now().isoformat() }, f)

# --- Fetch GNews AI Articles ---
def fetch_ai_news():
    if not should_fetch_fresh_news():
        print("⏱ Using cached news (not time to fetch yet)")
        return load_cache()

    print("🌐 Fetching fresh news from GNews...")
    query = '("GPT-4o" OR "Claude" OR "Mistral" OR "Anthropic" OR "OpenAI" OR "Google DeepMind" OR "Agent AI")'
    params = {
        "q": query,
        "lang": "en",
        "max": 5,
        "apikey": GNEWS_API_KEY
    }

    response = requests.get("https://gnews.io/api/v4/search", params=params)
    print(f"Querying GNews: {response.url}")
    if response.status_code != 200:
        print(f"GNews error: {response.status_code}")
        return load_cache()

    articles = response.json().get("articles", [])
    cache = load_cache()
    updated = False
    final_stories = []

    for a in articles:
        title_en = a.get("title", "").strip()
        summary_en = a.get("description", "").strip()
        url = a.get("url")

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
