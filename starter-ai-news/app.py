import os, json, time, hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any
import requests
from flask import Flask, render_template, request, abort, jsonify

# ----------------------------
# App / Config
# ----------------------------
app = Flask(__name__)

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")

# cache (English-only)
CACHE_PATH = Path("data/news_cache.json")
CACHE_TTL_MINUTES = int(os.getenv("CACHE_TTL_MINUTES", "60"))
CACHE_VERSION = "en-only-v3"  # bump to invalidate any old bilingual caches

# how many stories to display total
MAX_STORIES = 12

# default AI query
GNEWS_QUERY = '("GPT-4o" OR "Claude" OR "Mistral" OR "Anthropic" OR "OpenAI" OR "Google DeepMind" OR "Agent AI")'
NEWSDATA_QUERY = "AI OR artificial intelligence OR generative AI OR OpenAI OR Anthropic OR Mistral OR DeepMind"

# ----------------------------
# Routes (pages)
# ----------------------------
@app.get("/")
def index():
    stories = ensure_cache_and_get()
    return render_template("index.html", stories=stories, cache_bust=CACHE_VERSION)

@app.get("/markets")
def markets():
    # uses your existing templates/markets.html
    return render_template("markets.html", cache_bust=CACHE_VERSION)

# optional: quick route list to verify what's registered
@app.get("/_routes")
def _routes():
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}

# Healthcheck (Railway)
@app.get("/healthz")
def healthz():
    return {"ok": True, "time": time.time(), "version": CACHE_VERSION}

# ----------------------------
# Prices API: Yahoo first, Stooq fallback
# ----------------------------
_YCHART_CACHE: Dict = {}        # key: (symbol, range, interval) -> (expires_epoch, payload)
_YCHART_TTL_SEC = 60 * 5        # cache 5 minutes

def _yahoo_price_history(symbol: str, range_: str, interval: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "range": range_,
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits",
        "region": "US",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    if r.status_code != 200:
        return []

    j = r.json()
    result = (j.get("chart") or {}).get("result") or []
    if not result:
        return []

    res = result[0]
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]

    open_  = q.get("open")   or []
    high   = q.get("high")   or []
    low    = q.get("low")    or []
    close  = q.get("close")  or []
    volume = q.get("volume") or []

    candles = []
    for i, t in enumerate(ts):
        c = close[i] if i < len(close) else None
        if isinstance(c, (int, float)):
            candles.append({
                "t": int(t) * 1000,  # ms
                "o": open_[i]  if i < len(open_)  else None,
                "h": high[i]   if i < len(high)   else None,
                "l": low[i]    if i < len(low)    else None,
                "c": c,
                "v": volume[i] if i < len(volume) else None,
            })
    return candles

def _stooq_symbol(symbol: str) -> str:
    # Stooq uses lowercase + ".us" for U.S. tickers (NVDA, MSFT, GOOGL, AMZN, TSM)
    return f"{symbol.lower()}.us"

def _stooq_price_history(symbol: str, range_: str):
    s = _stooq_symbol(symbol)
    url = f"https://stooq.com/q/d/l/?s={s}&i=d"
    r = requests.get(url, timeout=15)
    if r.status_code != 200 or not r.text or "Date,Open,High,Low,Close,Volume" not in r.text:
        return []

    lines = r.text.strip().splitlines()
    rows = lines[1:]  # skip header

    # Determine how many days to keep based on range
    today = date.today()
    if range_ == "1d":
        want_days = 1
    elif range_ == "5d":
        want_days = 5
    elif range_ == "1mo":
        want_days = 32
    elif range_ == "6mo":
        want_days = 190
    elif range_ == "ytd":
        want_days = (today - date(today.year, 1, 1)).days + 1
    elif range_ == "1y":
        want_days = 370
    elif range_ == "5y":
        want_days = 5 * 370
    else:  # "max"
        want_days = len(rows)

    rows = rows[-want_days:]

    candles = []
    for line in rows:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        dstr, _o, _h, _l, c = parts[:5]
        try:
            # Noon UTC for plotting on a daily series
            ts = datetime.strptime(dstr, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            t_ms = int(ts) * 1000 + (12 * 3600 * 1000)
            c_val = float(c)
            candles.append({"t": t_ms, "o": None, "h": None, "l": None, "c": c_val, "v": None})
        except Exception:
            continue
    return candles

@app.get("/api/price_history")
def api_price_history():
    symbol   = (request.args.get("symbol") or "TSM").upper()
    range_   = request.args.get("range") or "ytd"
    interval = request.args.get("interval") or "1d"

    allowed_ranges = {"1d","5d","1mo","6mo","ytd","1y","5y","max"}
    allowed_intervals = {"5m","15m","1d","1wk","1mo"}
    if range_ not in allowed_ranges or interval not in allowed_intervals:
        abort(400)

    key = (symbol, range_, interval)
    now = time.time()
    cached = _YCHART_CACHE.get(key)
    if cached and cached[0] > now:
        return jsonify(cached[1])

    # Try Yahoo first (intraday capable), then Stooq (daily)
    try:
        candles = _yahoo_price_history(symbol, range_, interval)
    except Exception:
        candles = []

    if not candles:
        try:
            candles = _stooq_price_history(symbol, range_)
        except Exception:
            candles = []

    payload = {"symbol": symbol, "range": range_, "interval": interval, "candles": candles}
    _YCHART_CACHE[key] = (now + _YCHART_TTL_SEC, payload)
    return jsonify(payload)

# ----------------------------
# Utility
# ----------------------------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def read_cache() -> Dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_cache(payload: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def cache_is_fresh(cache: Dict[str, Any]) -> bool:
    if not cache or cache.get("version") != CACHE_VERSION:
        return False
    ts = cache.get("created_at")
    if not ts:
        return False
    try:
        created = datetime.fromisoformat(ts)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - created) < timedelta(minutes=CACHE_TTL_MINUTES)

def domain(u: str) -> str:
    try:
        return requests.utils.urlparse(u).netloc.lower()
    except Exception:
        return ""

def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

# ----------------------------
# News fetchers (EN only)
# ----------------------------
def fetch_gnews() -> List[Dict[str, Any]]:
    if not GNEWS_API_KEY:
        return []
    url = "https://gnews.io/api/v4/search"
    params = {
        "q": GNEWS_QUERY,
        "lang": "en",
        "max": 10,
        "token": GNEWS_API_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        articles = data.get("articles", [])
        out = []
        for a in articles:
            out.append({
                "id": _h(a.get("url","")),
                "source": a.get("source", {}).get("name") or domain(a.get("url","")) or "GNews",
                "title": a.get("title") or "",
                "summary": a.get("description") or "",
                "url": a.get("url") or "",
                "image": a.get("image") or "",
                "published_at": a.get("publishedAt") or "",
            })
        return out
    except Exception:
        return []

def fetch_newsdata() -> List[Dict[str, Any]]:
    if not NEWSDATA_API_KEY:
        return []
    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "q": NEWSDATA_QUERY,
        "language": "en",
        "country": "us,gb,ca,au",
        "page": 1,
        "size": 10
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results", []) or []
        out = []
        for a in results:
            u = a.get("link") or ""
            out.append({
                "id": _h(u),
                "source": (a.get("source_id") or domain(u) or "newsdata").title(),
                "title": a.get("title") or "",
                "summary": a.get("description") or a.get("content") or "",
                "url": u,
                "image": (a.get("image_url") or ""),
                "published_at": a.get("pubDate") or "",
            })
        return out
    except Exception:
        return []

# ----------------------------
# Post-processing
# ----------------------------
def dedupe(stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for s in stories:
        key = (s.get("title","").strip().lower(), domain(s.get("url","")))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out

def add_badges(stories: List[Dict[str, Any]]) -> None:
    # Simple keyword-based badges. Extend at will.
    for s in stories:
        t = f"{s.get('title','')} {s.get('summary','')}".lower()
        badges = []
        if any(k in t for k in ["revenue", "earnings", "ipo", "stock", "market", "guidance", "quarter"]):
            badges.append("Finance")
        if any(k in t for k in ["model", "gpt", "llama", "mistral", "mixtral", "inference", "fine-tune", "weights"]):
            badges.append("Model")
        if any(k in t for k in ["openai", "anthropic", "google", "deepmind", "microsoft", "meta", "nvidia", "amazon"]):
            badges.append("Company")
        if not badges:
            badges = ["AI"]
        s["badges"] = badges

def sort_by_date(stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _ts(s: Dict[str, Any]) -> float:
        p = s.get("published_at") or ""
        try:
            return datetime.fromisoformat(p.replace("Z","+00:00")).timestamp()
        except Exception:
            return 0.0
    return sorted(stories, key=_ts, reverse=True)

# ----------------------------
# Core
# ----------------------------
def get_fresh_stories() -> List[Dict[str, Any]]:
    gnews = fetch_gnews()
    newsdata = fetch_newsdata()
    merged = dedupe(gnews + newsdata)
    add_badges(merged)
    return sort_by_date(merged)[:MAX_STORIES]

def ensure_cache_and_get() -> List[Dict[str, Any]]:
    cache = read_cache()
    if cache_is_fresh(cache):
        return cache.get("stories", [])[:MAX_STORIES]
    stories = get_fresh_stories()
    write_cache({
        "version": CACHE_VERSION,
        "created_at": now_utc_iso(),
        "stories": stories
    })
    return stories

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    app.run(debug=True)
