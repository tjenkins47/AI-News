# app.py — AI News v2 (AI + Finance)
# Cleanups: remove duplicate /markets route, unify NewsData cooldown, single cache path,
# fix set_lang redirect, keep preview filter & Chart API.

import os, time, json, re, html, difflib, urllib.parse, datetime as dt, logging, requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Iterable
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from dotenv import load_dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # In prod, python-dotenv may not be installed; that's fine.
    pass

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ai-news")

# API Keys / Flags
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "").strip()
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "").strip()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
TRANSLATE_ENABLED = os.getenv("TRANSLATE_ENABLED", "0").strip() in ("1", "true", "True", "yes", "on")

# Session secret (needed for language toggle)
# Use env key if provided; otherwise generate a temporary one so the app doesn't 500.
secret_from_env = os.getenv("SECRET_KEY")
if secret_from_env:
    app.secret_key = secret_from_env
else:
    app.secret_key = os.urandom(32)
    app.logger.warning("SECRET_KEY not set; generated a temporary key for this process.")


# Static cache-bust
CACHE_VERSION = int(os.getenv("CACHE_VERSION", "5"))

@app.context_processor
def inject_i18n():
    return {"current_lang": session.get("lang", "EN")}

@app.context_processor
def inject_cache_bust():
    return {"cache_bust": CACHE_VERSION}

# Paths / Admin
DATA_DIR = "data"
NEWS_CACHE_PATH = os.path.join(DATA_DIR, f"news_cache_{CACHE_VERSION}.json")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # optional simple admin token

# Rate-limit cooldown (NewsData)
NEWSDATA_COOLDOWN_SEC = 15 * 60  # 15 minutes
_newsd_cooldown_until = 0
def newsdata_on_cooldown() -> bool:
    return time.time() < _newsd_cooldown_until

# Simple per-key TTL cache (e.g., OHLC)
_CACHE: Dict[str, Any] = {}
_CACHE_TTL_SEC = 10 * 60
def _cache_get(key):
    rec = _CACHE.get(key)
    if not rec:
        return None
    ts, data = rec
    return data if (time.time() - ts) < _CACHE_TTL_SEC else None
def _cache_put(key, data):
    _CACHE[key] = (time.time(), data)

# --------------------------------------------------------------------------------------
# Language toggle
# --------------------------------------------------------------------------------------
# Language toggle — guaranteed endpoint name
@app.route("/set_lang", methods=["GET"], endpoint="set_lang")
def set_lang_route():
    from flask import request, session, redirect, url_for
    lang = (request.args.get("lang", "en") or "en").lower()
    if lang not in ("en", "fr"):
        lang = "en"
    session["lang"] = lang.upper()
    nxt = request.args.get("next") or request.referrer or url_for("home")
    return redirect(nxt)


# --------------------------------------------------------------------------------------
# Template filters
# --------------------------------------------------------------------------------------
@app.template_filter('preview')
def preview(text, limit=380):
    """
    Strip HTML, collapse whitespace, and truncate with a word-safe ellipsis.
    Returns a plain string (safe to render).
    """
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<[^>]+>", " ", s)          # strip tags
    s = html.unescape(s)                     # decode entities
    s = re.sub(r"\s+", " ", s).strip()       # collapse whitespace
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]        # avoid mid-word cut
    return f"{cut}…"

# --------------------------------------------------------------------------------------
# NewsData wrapper with cooldown
# --------------------------------------------------------------------------------------
def newsdata_get(url: str, params: dict):
    """
    Wrapper around requests.get for NewsData.io that:
    - skips calls while in cooldown
    - starts cooldown on HTTP 429
    - logs concise messages
    Returns parsed JSON dict on success, or None on skip/error.
    """
    global _newsd_cooldown_until
    if newsdata_on_cooldown():
        app.logger.info("NewsData: on cooldown; skipping call.")
        return None
    try:
        r = requests.get(url, params=params, timeout=20)
    except Exception as e:
        app.logger.warning(f"NewsData network error: {e}")
        return None
    if r.status_code == 429:
        _newsd_cooldown_until = time.time() + NEWSDATA_COOLDOWN_SEC
        app.logger.warning("NewsData 429 rate limit — cooling down for %d sec.", NEWSDATA_COOLDOWN_SEC)
        return None
    if r.status_code >= 400:
        app.logger.warning("NewsData HTTP %s: %s", r.status_code, r.text[:200])
        return None
    try:
        return r.json()
    except Exception:
        app.logger.warning("NewsData: failed to parse JSON.")
        return None

# --------------------------------------------------------------------------------------
# Finance: Yahoo chart fetcher
# --------------------------------------------------------------------------------------
def fetch_yahoo_chart(symbol: str, range_: str, interval: str):
    """
    Returns {"symbol": "TSM", "points": [ {t,o,h,l,c,v}, ... ]}
    """
    import requests
    from datetime import datetime, timezone

    symbol = symbol.upper()
    range_ = range_.lower()
    interval = interval.lower()

    ck = f"{symbol}|{range_}|{interval}"
    cached = _cache_get(ck)
    if cached:
        return cached

    def _trim_ytd(pts):
        if range_ != "ytd" or not pts:
            return pts
        jan1 = datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
        return [p for p in pts if p["t"] >= jan1]

    def _build_points_from_yahoo(payload):
        result = payload.get("chart", {}).get("result", [{}])[0]
        ts_list = result.get("timestamp") or []
        ind = result.get("indicators", {}).get("quote", [{}])[0]
        o = ind.get("open", []) or []
        h = ind.get("high", []) or []
        l = ind.get("low", []) or []
        c = ind.get("close", []) or []
        v = ind.get("volume", []) or []
        pts = []
        for i, ts in enumerate(ts_list):
            if ts is None or i >= len(c) or c[i] in (None, "null"):
                continue
            pts.append({
                "t": int(ts) * 1000,
                "o": None if i >= len(o) else o[i],
                "h": None if i >= len(h) else h[i],
                "l": None if i >= len(l) else l[i],
                "c": c[i],
                "v": None if i >= len(v) else v[i],
            })
        return pts

    def _try_rapidapi():
        key = os.getenv("YF_RAPIDAPI_KEY", "").strip()
        if not key:
            return []
        url = "https://apidojo-yahoo-finance-v1.p.rapidapi.com/stock/v3/get-chart"
        wire_range = "1y" if range_ == "ytd" else range_
        params = {"symbol": symbol, "interval": interval, "range": wire_range, "region": "US"}
        headers = {
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": "apidojo-yahoo-finance-v1.p.rapidapi.com",
        }
        r = requests.get(url, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        pts = _build_points_from_yahoo(r.json())
        return _trim_ytd(pts)

    def _try_yfinance():
        try:
            import yfinance as yf
            import pandas as pd
        except Exception:
            return []  # yfinance not installed locally
        rng_map = {
            "1d": ("1d", "5m"),
            "5d": ("5d", "15m"),
            "1mo": ("1mo", "1d"),
            "6mo": ("6mo", "1d"),
            "ytd": ("1y", "1d"),
            "1y": ("1y", "1d"),
            "5y": ("5y", "1wk"),
            "max": ("max", "1mo"),
        }
        r_, i_ = rng_map.get(range_, ("6mo", "1d"))
        if interval != "auto":
            i_ = interval
        df = yf.Ticker(symbol).history(period=r_, interval=i_, auto_adjust=False)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        if range_ == "ytd":
            year = pd.Timestamp.utcnow().year
            df = df[df["Date"].dt.year == year]
        pts = []
        for _, row in df.iterrows():
            ts = int(pd.Timestamp(row["Date"]).timestamp() * 1000)
            close = row.get("Close")
            if close is None:
                continue
            pts.append({
                "t": ts,
                "o": float(row.get("Open")) if pd.notna(row.get("Open")) else None,
                "h": float(row.get("High")) if pd.notna(row.get("High")) else None,
                "l": float(row.get("Low")) if pd.notna(row.get("Low")) else None,
                "c": float(close) if pd.notna(close) else None,
                "v": float(row.get("Volume")) if pd.notna(row.get("Volume")) else None,
            })
        return pts

    source = "rapidapi"
    pts = _try_rapidapi()
    if not pts:
        pts = _try_yfinance()
        source = "yfinance" if pts else "none"

    data = {"symbol": symbol, "points": pts}
    _cache_put(ck, data)
    try:
        print(f"OHLC {symbol} {range_} {interval}: {len(pts)} points via {source}")
    except Exception:
        pass
    return data

# --------------------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------------------
@app.route("/admin/flush-cache/<token>")
def flush_cache(token):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        if os.path.exists(NEWS_CACHE_PATH):
            os.remove(NEWS_CACHE_PATH)
        return {"ok": True, "message": "cache cleared"}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

def _mask(s: str) -> str:
    if not s: return "(missing)"
    return s[:3] + "…" + s[-3:] if len(s) > 6 else "***"

log.info("GNEWS_API_KEY: %s | NEWSDATA_API_KEY: %s | GOOGLE_API_KEY: %s | TRANSLATE_ENABLED=%s",
         _mask(GNEWS_API_KEY), _mask(NEWSDATA_API_KEY), _mask(GOOGLE_API_KEY), TRANSLATE_ENABLED)

# --------------------------------------------------------------------------------------
# News queries / settings
# --------------------------------------------------------------------------------------
MAX_TOTAL_STORIES = 12
CACHE_TTL_MINUTES = 45

GNEWS_QUERIES = [
    '"OpenAI" OR Anthropic OR "Google DeepMind"',
    'AI OR "artificial intelligence" OR LLM',
    'Nvidia OR "AI chips" OR semiconductor',
    'Microsoft OR Alphabet OR Google',
    'Meta OR Amazon OR AMD',
    'Mistral OR "Agent AI"',
]
NEWSDATA_TECH_QUERIES = [
    'AI OR "artificial intelligence"',
    '"large language model" OR LLM',
    'OpenAI OR Anthropic OR Mistral',
    '"Google DeepMind" OR "Agent AI"',
]
NEWSDATA_BIZ_QUERIES = [
    'AI earnings',
    'AI chips OR Nvidia',
    'Microsoft AND AI',
    'Google OR Alphabet AND AI',
    'Meta AND AI',
    'Amazon AND AI',
    'AMD AND AI',
]

# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
def _norm_title_key(title: str) -> str:
    toks = _WORD_RE.findall((title or "").lower())
    return " ".join(toks)
def _url_key(url: str) -> str:
    try:
        u = urllib.parse.urlparse(url or "")
        return f"{(u.netloc or '').lower()}{(u.path or '').lower()}"
    except Exception:
        return (url or "").lower().strip()
def _fuzzy_dup(a: str, b: str, ratio_threshold: float) -> bool:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio() >= ratio_threshold
def _parse_iso_to_naive_utc(ts: str) -> dt.datetime:
    if not ts:
        return dt.datetime.utcnow()
    t = ts.strip().replace("UTC", "+0000")
    try:
        if " " in t and "T" not in t:
            try:
                aware = dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S %z")
                return aware.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                try:
                    naive = dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                    return naive
                except Exception:
                    pass
            t = t.replace(" ", "T").replace("+0000", "+00:00")
        dtobj = dt.datetime.fromisoformat(t)
        if dtobj.tzinfo is not None:
            return dtobj.astimezone(timezone.utc).replace(tzinfo=None)
        return dtobj
    except Exception:
        return dt.datetime.utcnow()
def _title_text(s: Dict[str, Any]) -> str:
    t = s.get("title")
    if isinstance(t, dict):
        return (t.get("en") or t.get("fr") or "").strip()
    return (t or "").strip()

# De-dupe
def deduplicate_by_token_set(articles, threshold: int = 90, max_per_topic: int = 2):
    ratio_threshold = max(0.0, min(1.0, threshold / 100.0))
    seen_title_keys, seen_url_keys = set(), set()
    kept = []
    topic_counts = {}
    def topic_key(story: Dict[str, Any]) -> str:
        text = (_title_text(story) + " " + (story.get("summary", {}).get("en") or "")).lower()
        if "lawsuit" in text or "sue" in text:
            return "lawsuit"
        if "earnings" in text or "revenue" in text or "investment" in text:
            return "finance"
        if "nvidia" in text or "chip" in text or "semiconductor" in text:
            return "nvidia"
        if "microsoft" in text:
            return "microsoft"
        if "google" in text or "alphabet" in text or "deepmind" in text:
            return "google"
        if "meta" in text:
            return "meta"
        if "amazon" in text:
            return "amazon"
        return "other"
    for s in articles or []:
        title = _title_text(s)
        url = (s.get("url") or "").strip()
        summary = (s.get("summary", {}).get("en") or "").strip()
        tkey = _norm_title_key(title)
        ukey = _url_key(url)
        if tkey in seen_title_keys or (ukey and ukey in seen_url_keys):
            continue
        if any(_fuzzy_dup(title + " " + summary, _title_text(k) + " " + (k.get("summary", {}).get("en") or ""), ratio_threshold) for k in kept):
            continue
        tcluster = topic_key(s)
        if topic_counts.get(tcluster, 0) >= max_per_topic:
            continue
        topic_counts[tcluster] = topic_counts.get(tcluster, 0) + 1
        seen_title_keys.add(tkey)
        if ukey: seen_url_keys.add(ukey)
        kept.append(s)
    return kept

def merge_sort_cap(all_stories: Iterable[Dict[str, Any]], cap: int = MAX_TOTAL_STORIES) -> List[Dict[str, Any]]:
    def ts(s):
        val = s.get("timestamp") or s.get("published_at") or ""
        try:
            return _parse_iso_to_naive_utc(val)
        except Exception:
            return dt.datetime.min
    merged = list(all_stories)
    merged.sort(key=ts, reverse=True)
    return merged[:cap]

# --------------------------------------------------------------------------------------
# Helpers (translate, classify, cache)
# --------------------------------------------------------------------------------------
def translate_to_french(text: str) -> str:
    text = text or ""
    if not text:
        return ""
    if not TRANSLATE_ENABLED or not GOOGLE_API_KEY:
        return text  # disabled → echo EN
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"q": text, "target": "fr", "format": "text", "key": GOOGLE_API_KEY}
    try:
        resp = requests.post(url, data=params, timeout=8)
        if resp.status_code == 200:
            return resp.json()["data"]["translations"][0]["translatedText"]
        else:
            log.warning("Translate failed %s: %s", resp.status_code, resp.text[:140])
    except Exception as e:
        log.warning("Translate exception: %s", e)
    return text

def classify_article(title_en: str, summary_en: str) -> List[str]:
    text = f"{title_en} {summary_en}".lower()
    cats = set()
    if any(k in text for k in [
        "earnings", "revenue", "profit", "quarter", "guidance", "valuation",
        "ipo", "stock", "shares", "market cap", "dividend", "buyback",
        "funding", "raised", "seed", "series a", "series b", "venture",
        "acquisition", "merger", "m&a", "spinoff"
    ]): cats.add("finance")
    if any(k in text for k in ["lawsuit", "sues", "sued", "settlement", "complaint", "class action"]): cats.add("Law")
    if any(k in text for k in [
        "regulation", "regulatory", "eu ai act", "sec", "ftc", "doj",
        "bill", "senate", "house committee", "white house", "executive order",
        "ofcom", "ico (uk)"
    ]): cats.add("Policy")
    if any(k in text for k in ["safety", "red team", "alignment", "guardrail", "mitigation", "harm reduction"]): cats.add("Safety")
    if any(k in text for k in ["breach", "leak", "ransomware", "compromise", "exploit", "zero-day", "privacy"]): cats.add("Security")
    if any(k in text for k in ["nvidia", "gpu", "h100", "h200", "blackwell", "chip", "semiconductor", "data center", "accelerator"]): cats.add("Hardware")
    if any(k in text for k in ["benchmark", "paper", "arxiv", "sota", "state-of-the-art", "researchers", "dataset"]): cats.add("Research")
    if any(k in text for k in ["open source", "apache-2.0", "mit license", "oss"]): cats.add("Open Source")
    if any(k in text for k in ["launch", "rollout", "release", "update", "feature", "preview", "private beta", "general availability"]): cats.add("Product")
    company_hit = any(k in text for k in [
        "openai", "anthropic", "mistral", "deepmind", "google", "alphabet",
        "microsoft", "meta", "amazon", "amd", "xai", "databricks", "snowflake"
    ])
    if any(k in text for k in [
        "gpt", "chatgpt", "gpt-4", "gpt-4o", "gpt-4.1", "gpt-5",
        "claude", "llama", "gemma", "gemini", "grok", "mistral", "mixtral",
        "sonnet", "haiku", "opus", "sora"
    ]) or "model" in text: cats.add("Model")
    if not cats:
        cats.add("Product" if company_hit else "AI")
    order = ["Model", "Hardware", "Research", "Open Source", "Product", "Safety", "Security", "Policy", "Law", "finance", "AI"]
    final = [c for c in order if c in cats]
    return final or ["AI"]

def load_cache() -> List[Dict[str, Any]]:
    try:
        if not os.path.exists(NEWS_CACHE_PATH):
            return []
        with open(NEWS_CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            log.info("Loaded legacy cache list: %d items", len(raw)); return raw
        if isinstance(raw, dict) and isinstance(raw.get("news"), list):
            items = raw["news"]; log.info("Loaded cache dict: %d items", len(items)); return items
        log.warning("Cache structure unexpected; ignoring.")
        return []
    except Exception as e:
        log.warning("Cache load error: %s", e); return []

def save_cache(items: List[Dict[str, Any]]) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        payload = {"cached_at": datetime.utcnow().isoformat(), "news": items}
        with open(NEWS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("Cache saved: %d items", len(items))
    except Exception as e:
        log.warning("Cache save error: %s", e)

# --------------------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------------------
def _normalize_story(title_en: str, summary_en: str, url: str, image_url: str,
                     source: str, pub: str, tags: List[str] | None) -> Dict[str, Any]:
    cats = classify_article(title_en, summary_en)
    out_tags = list(tags) if tags else ["ai"]
    if "finance" in cats and "finance" not in (t.lower() for t in out_tags):
        out_tags.append("finance")
    return {
        "timestamp": _parse_iso_to_naive_utc(pub).isoformat(),
        "title": {"en": title_en, "fr": translate_to_french(title_en)},
        "summary": {"en": summary_en, "fr": translate_to_french(summary_en)},
        "url": url,
        "image_url": image_url or None,
        "source": source,
        "categories": cats,
        "tags": out_tags,
    }

def fetch_gnews_articles_for_query(q: str, max_items: int = 8) -> List[Dict[str, Any]]:
    if not GNEWS_API_KEY:
        return []
    base = "https://gnews.io/api/v4/search"
    params = {"q": q, "lang": "en", "max": str(max_items), "token": GNEWS_API_KEY, "sortby": "publishedAt"}
    r = requests.get(base, params=params, timeout=12)
    if r.status_code != 200:
        log.warning("GNews error %s for q='%s': %s", r.status_code, q, r.text[:140]); return []
    return (r.json() or {}).get("articles", [])

def fetch_gnews_ai(total_target: int = 8) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for q in GNEWS_QUERIES:
        if len(collected) >= total_target: break
        remaining = total_target - len(collected)
        raw = fetch_gnews_articles_for_query(q, max_items=min(8, remaining))
        for a in raw:
            title_en = a.get("title", "") or ""
            desc_en = a.get("description", "") or ""
            published = a.get("publishedAt") or a.get("published_at") or ""
            collected.append(_normalize_story(
                title_en, desc_en, a.get("url"), a.get("image") or a.get("image_url"),
                (a.get("source") or {}).get("name", "GNews"), published, ["ai"]
            ))
    log.info("GNews normalized stories (multi-query): %d", len(collected))
    return collected

def _newsdata_fetch_queries(category: str, queries: List[str], total_target: int, finance: bool) -> List[Dict[str, Any]]:
    if not NEWSDATA_API_KEY:
        return []
    base = "https://newsdata.io/api/1/latest"
    collected: List[Dict[str, Any]] = []
    for q in queries:
        if len(collected) >= total_target: break
        next_page = None
        while len(collected) < total_target:
            params = {"apikey": NEWSDATA_API_KEY, "category": category, "language": "en", "q": q}
            if next_page: params["page"] = next_page
            data = newsdata_get(base, params)
            if not data:
                break
            results = data.get("results", [])
            for r in results:
                title_en = (r.get("title") or "").strip()
                url = r.get("link") or r.get("url") or ""
                if not title_en or not url: continue
                src = (r.get("source_id") or r.get("source") or "NewsData").strip()
                summary_en = (r.get("description") or r.get("content") or "").strip()
                pub = r.get("pubDate") or r.get("published_at") or ""
                collected.append(_normalize_story(
                    title_en, summary_en, url, r.get("image_url") or r.get("image"),
                    src, pub, (["finance","ai"] if finance else ["ai"])
                ))
                if len(collected) >= total_target: break
            next_page = (data or {}).get("nextPage")
            if not next_page or not results: break
    log.info("NewsData %s normalized stories (multi-query): %d", category, len(collected))
    return collected

def fetch_newsdata_ai(total_target: int = 6) -> List[Dict[str, Any]]:
    return _newsdata_fetch_queries("technology", NEWSDATA_TECH_QUERIES, total_target, finance=False)
def fetch_newsdata_business_ai(total_target: int = 6) -> List[Dict[str, Any]]:
    return _newsdata_fetch_queries("business", NEWSDATA_BIZ_QUERIES, total_target, finance=True)

# --------------------------------------------------------------------------------------
# Unified builder
# --------------------------------------------------------------------------------------
def fetch_ai_news() -> List[Dict[str, Any]]:
    try:
        gnews = fetch_gnews_ai(8)
        tech = fetch_newsdata_ai(6)
        finance = fetch_newsdata_business_ai(6)
        log.info("Pre-dedupe counts | GNews: %d | NewsData-tech: %d | NewsData-biz: %d", len(gnews), len(tech), len(finance))
        combined = deduplicate_by_token_set([*gnews, *tech, *finance], threshold=92)
        log.info("Post-dedupe count: %d", len(combined))
        final = merge_sort_cap(combined, cap=MAX_TOTAL_STORIES)
        log.info("Final (capped) count: %d", len(final))
        if final:
            save_cache(final)
            return final
        cached = load_cache()
        if cached:
            log.warning("Using cached items (live fetch empty): %d", len(cached))
            return cached[:MAX_TOTAL_STORIES]
        log.error("No stories available from live fetch or cache.")
        return []
    except Exception as e:
        log.error("fetch_ai_news unexpected error: %s", e)
        cached = load_cache()
        if cached:
            log.warning("Error fallback to cache: %d", len(cached))
            return cached[:MAX_TOTAL_STORIES]
        return []

# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
@app.route("/")
def home():
    items = fetch_ai_news()
    return render_template("index.html", news_items=items)

@app.route("/api/news")
def get_news():
    return jsonify(fetch_ai_news())

# Markets (single definition; hide language dropdown on this page)
@app.route("/markets", methods=["GET"], endpoint="markets_view")
def markets_view():
    return render_template("markets.html", title="Markets", cache_bust=CACHE_VERSION, hide_lang=True)

# OHLC API
@app.route("/api/ohlc/<symbol>", methods=["GET"], endpoint="api_ohlc")
def api_ohlc_route(symbol):
    range_ = request.args.get("range", "6mo")
    interval = request.args.get("interval", "1d")
    data = fetch_yahoo_chart(symbol, range_, interval)
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp

# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(debug=True)
