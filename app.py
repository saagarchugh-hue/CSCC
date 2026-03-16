"""
Flask server for the Merchant Success Command Center dashboard.
Serves the dashboard and provides AI-backed API endpoints:
  - POST /api/generate-email — generate a reach-out email from merchant context
  - GET  /api/news?merchant=... — fetch latest news about the merchant

Set environment variables:
  OPENAI_API_KEY — required for email generation
  GEMINI_API_KEY — optional; for "Latest news" via Gemini + Google Search grounding (preferred)
  NEWS_API_KEY   — optional; from https://newsapi.org/ (free tier) for news
  SERPER_API_KEY — optional; from https://serper.dev for news if Gemini unused

Run: flask run --host=0.0.0.0  (or: python app.py)
Then open http://<this-machine-ip>:5000 for team access.
"""
import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")

# Paths
ROOT = Path(__file__).resolve().parent
DASHBOARD_HTML = ROOT / "dashboard.html"


def get_openai_client():
    try:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        return OpenAI(api_key=key)
    except Exception:
        return None


# User-facing messages when deployed without API keys (no env vars set)
MSG_EMAIL_NOT_CONFIGURED = "Email generation is not configured for this deployment. Add OPENAI_API_KEY to enable it."
MSG_NEWS_NOT_CONFIGURED = "Latest news is not configured for this deployment. Add GEMINI_API_KEY, NEWS_API_KEY, or SERPER_API_KEY to enable it."


def generate_email_via_openai(payload):
    """Generate a short professional reach-out email using OpenAI."""
    client = get_openai_client()
    if not client:
        return None, MSG_EMAIL_NOT_CONFIGURED

    merchant = payload.get("merchant", "")
    vertical = payload.get("vertical", "")
    tier = payload.get("tier", "")
    engagement_month = payload.get("engagement_month_label", "")
    engagement_type = payload.get("engagement_type", "")
    playbook = payload.get("playbook", "")
    peak_months = payload.get("peak_months", "")
    next_action = payload.get("next_action", "")
    owner = payload.get("owner", "")

    prompt = f"""You are a Client Success manager at Affirm. Write a short, professional reach-out email to the merchant contact at "{merchant}" to set up planning for their upcoming peak season.

Context:
- Vertical: {vertical}. Tier: {tier}.
- Engagement month (when we're reaching out): {engagement_month}. Phase: {engagement_type}.
- Their peak months: {peak_months}. Playbook focus: {playbook}.
- Suggested next step: {next_action}.
- CSM/Owner: {owner}.

Write one concise email (3–5 sentences): friendly, specific to their planning cycle and time of year, and ending with a clear ask (e.g. schedule a planning call or confirm promo details). Do not include subject line or signatures. Use a professional but warm tone."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text, None
    except Exception as e:
        return None, str(e)


def fetch_news_newsapi(merchant_name: str, limit: int = 8):
    """Fetch recent news using News API (newsapi.org)."""
    key = os.environ.get("NEWS_API_KEY")
    if not key:
        return None, "NEWS_API_KEY not set. Get a key at https://newsapi.org/"

    import urllib.parse
    import urllib.request
    q = urllib.parse.quote_plus(merchant_name)
    url = f"https://newsapi.org/v2/everything?q={q}&language=en&sortBy=publishedAt&pageSize={limit}&apiKey={key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return None, str(e)

    articles = data.get("articles") or []
    items = []
    for a in articles:
        if not a.get("title") or a.get("title") == "[Removed]":
            continue
        items.append({
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "source": a.get("source", {}).get("name", ""),
            "published": a.get("publishedAt", ""),
        })
    return items, None


def fetch_news_serper(merchant_name: str, limit: int = 8):
    """Fetch news/search results using Serper (serper.dev)."""
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        return None, "SERPER_API_KEY not set."

    import urllib.request
    req = urllib.request.Request(
        "https://google.serper.dev/news",
        data=json.dumps({"q": f"{merchant_name} company news", "num": limit}).encode(),
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return None, str(e)

    news = data.get("news", {}).get("organic", []) or []
    items = [
        {
            "title": n.get("title", ""),
            "url": n.get("url", ""),
            "source": n.get("source", ""),
            "published": n.get("date", ""),
        }
        for n in news
    ]
    return items, None


def fetch_news_gemini(merchant_name: str, limit: int = 8):
    """
    Fetch latest news about the merchant using Gemini with Google Search grounding.
    Returns (list of {title, url, source}, summary_text) or (None, error).
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, None, "GEMINI_API_KEY not set. Get a key at https://aistudio.google.com/apikey"

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None, None, "Install the Gemini SDK: pip install google-genai"

    client = genai.Client(api_key=key)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[grounding_tool])
    prompt = (
        f"List the latest news and recent developments about the company or brand: {merchant_name}. "
        f"Return a brief summary (2–3 sentences) and then list up to {limit} specific recent news items "
        "with clear titles and sources. Focus on business, product, or partnership news."
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=config,
        )
    except Exception as e:
        return None, None, str(e)

    if not response.candidates:
        return None, None, "No response from Gemini"

    candidate = response.candidates[0]
    summary = (response.text or "").strip()

    # Extract sources from grounding metadata (same shape as other news backends)
    items = []
    grounding = getattr(candidate, "grounding_metadata", None) or getattr(
        candidate, "groundingMetadata", None
    )
    if grounding:
        chunks = getattr(grounding, "grounding_chunks", None) or getattr(
            grounding, "groundingChunks", []
        ) or []
        for ch in chunks[:limit]:
            web = getattr(ch, "web", None)
            if not web:
                continue
            uri = getattr(web, "uri", "") or ""
            title = getattr(web, "title", "") or "Source"
            if uri:
                items.append({
                    "title": title if isinstance(title, str) else "Source",
                    "url": uri,
                    "source": title if isinstance(title, str) else "Web",
                    "published": "",
                })

    # If no chunks, still return summary so the UI can show it
    return items, summary, None


@app.route("/")
def index():
    if DASHBOARD_HTML.exists():
        return send_from_directory(ROOT, "dashboard.html")
    return "Dashboard not found. Run: python build_dashboard.py", 404


@app.route("/api/generate-email", methods=["POST"])
def api_generate_email():
    if request.method != "POST":
        return jsonify({"error": "Method not allowed"}), 405
    try:
        payload = request.get_json() or {}
    except Exception:
        payload = {}
    email, err = generate_email_via_openai(payload)
    if err:
        is_not_configured = err == MSG_EMAIL_NOT_CONFIGURED
        return jsonify({"error": err}), 400 if is_not_configured else 500
    return jsonify({"email": email})


@app.route("/api/news")
def api_news():
    merchant = request.args.get("merchant", "").strip()
    if not merchant:
        return jsonify({"error": "Missing merchant query"}), 400
    limit = min(15, max(1, int(request.args.get("limit", 8))))
    use_gemini = request.args.get("source", "").lower() == "gemini" or bool(os.environ.get("GEMINI_API_KEY"))

    # Prefer Gemini (Google Search grounding) if key is set; then News API; then Serper
    if use_gemini:
        items, summary, err = fetch_news_gemini(merchant, limit)
        if err:
            if "not set" in err or "Install" in err:
                items, err = fetch_news_newsapi(merchant, limit)
                if err and "not set" in err:
                    items, err = fetch_news_serper(merchant, limit)
                if err:
                    return jsonify({"error": MSG_NEWS_NOT_CONFIGURED}), 400
                return jsonify({"merchant": merchant, "articles": items})
            return jsonify({"error": err}), 500
        out = {"merchant": merchant, "articles": items}
        if summary:
            out["summary"] = summary
        return jsonify(out)

    items, err = fetch_news_newsapi(merchant, limit)
    if err and "not set" in err:
        items, err = fetch_news_serper(merchant, limit)
    if err:
        return jsonify({"error": MSG_NEWS_NOT_CONFIGURED}), 400
    return jsonify({"merchant": merchant, "articles": items})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
