"""
Flask server for the Merchant Success Command Center dashboard.
Serves the dashboard and provides AI-backed API endpoints:
  - POST /api/generate-email — generate a reach-out email from merchant context
  - GET  /api/news?merchant=... — fetch latest news about the merchant

Set environment variables:
  OPENAI_API_KEY — used for both "Generate email" and "Latest news" (one key for both)
  OPENAI_NEWS_MODEL — optional; model for news via Responses API + web_search (default: gpt-4o)
  GEMINI_API_KEY — optional; alternative for "Latest news" (Gemini + Google Search)
  NEWS_API_KEY   — optional; fallback for "Latest news"
  SERPER_API_KEY — optional; fallback for "Latest news"
  GOOGLE_SHEET_ID — optional; spreadsheet ID for live data (see HOSTING.md)
  GOOGLE_SHEET_GID — optional; sheet/tab gid (default 0)

Run: flask run --host=0.0.0.0  (or: python app.py)
Then open http://<this-machine-ip>:5000 for team access.
"""
import csv
import io
import json
import os
import urllib.request
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


def normalize_name(name: str) -> str:
    return " ".join(str(name or "").strip().split())


def read_merchants_from_google_sheet(sheet_id: str, gid: str = "0"):
    """
    Fetch a published Google Sheet as CSV and return
    (merchant_names, merchant_to_owner, merchant_to_gmv, merchant_to_legal, error).
    Expects columns like: Account, CSM, FY26 FC GMV (headers detected flexibly).
    """
    from CSCC import format_fy26_gmv

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "CSCC-Dashboard/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, None, None, None, str(e)
    if "Sign in" in raw or "sign in" in raw:
        return None, None, None, None, "Sheet is private. Publish to web: File → Share → Publish to web → choose this sheet → CSV."
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return None, None, None, None, "Sheet is empty."
    headers = [normalize_name(h) for h in rows[0]]
    name_col = 0
    owner_col = 1
    gmv_col = None
    for i, h in enumerate(headers):
        if not h:
            continue
        hl = h.lower()
        if "merchant" in hl or "name" in hl or "account" in hl:
            name_col = i
        if "csm" in hl or "owner" in hl:
            owner_col = i
        if "gmv" in hl or "fy26" in hl or "fc gmv" in hl:
            gmv_col = i
    names = []
    seen = set()
    merchant_to_owner = {}
    merchant_to_gmv = {}
    merchant_to_legal = {}
    legal_col = None
    for i, h in enumerate(headers):
        if not h:
            continue
        hl = h.lower()
        if ("legal" in hl and "gmv" not in hl) or hl in ("entity", "legal entity", "legal name"):
            legal_col = i
    for row in rows[1:]:
        if name_col >= len(row):
            continue
        name = normalize_name(row[name_col])
        if not name or name.lower() in ("all merchants", "new merchants"):
            continue
        if name.lower() in ("account", "merchant", "name"):
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
            owner = normalize_name(row[owner_col]) if owner_col < len(row) else ""
            merchant_to_owner[name] = owner or ""
            gmv_raw = row[gmv_col] if gmv_col is not None and gmv_col < len(row) else None
            merchant_to_gmv[name] = (
                format_fy26_gmv(gmv_raw) if gmv_raw is not None and str(gmv_raw).strip() != "" else ""
            )
            leg = row[legal_col] if legal_col is not None and legal_col < len(row) else None
            merchant_to_legal[name] = normalize_name(str(leg)) if leg is not None and str(leg).strip() else ""
    return names, merchant_to_owner, merchant_to_gmv, merchant_to_legal, None


# User-facing messages when deployed without API keys (no env vars set)
MSG_EMAIL_NOT_CONFIGURED = "Email generation is not configured for this deployment. Add OPENAI_API_KEY to enable it."
MSG_NEWS_NOT_CONFIGURED = "Latest news is not configured for this deployment. Add OPENAI_API_KEY (or GEMINI_API_KEY, NEWS_API_KEY, SERPER_API_KEY) in Railway Variables and redeploy."


def generate_email_via_openai(payload):
    """Generate a short CSM reach-out email (peak-season financing + performance learning) via OpenAI."""
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
    fy26_gmv = payload.get("fy26_fc_gmv", "")

    gmv_line = f"- FY26 FC GMV with Affirm (forecast / plan): {fy26_gmv}.\n" if str(fy26_gmv).strip() else ""

    prompt = f"""You are a Client Success manager at Affirm. Write a short, professional reach-out email to the merchant contact at "{merchant}" to set up planning for their upcoming peak season.

How Affirm works with merchants (use this naturally in the email—do not lecture, but reflect why the conversation matters):
- Affirm partners with merchants to implement **buy now, pay later / financing programs** that are designed to **lift conversion and order value**, especially around **seasonal peaks** and high-intent shopping periods.
- CSMs also help merchants use **competitive and historical performance data** (category benchmarks, prior-season learnings, program performance) so they can **iterate and improve** financing placement, messaging, and promos over time.

Merchant-specific context:
- Vertical: {vertical}. Tier: {tier}.
- Engagement month (when we're reaching out): {engagement_month}. Phase: {engagement_type}.
- Their peak months: {peak_months}. Playbook focus: {playbook}.
- Suggested next step: {next_action}.
- CSM: {owner}.
{gmv_line}

Write one concise email (3–5 sentences): tie the outreach to **peak-season readiness** and how Affirm financing can support **sales during their season**, and mention **learning from performance or benchmarks** where it fits (without making up numbers). End with a clear ask (e.g. schedule a planning call, align on promo or financing placement, or review last season’s learnings). Do not include a subject line or signatures. Professional but warm tone."""

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


def _openai_responses_text_and_citations(response, limit: int) -> tuple[str, list[dict]]:
    """Extract main text and url_citation sources from a Responses API result."""
    items: list[dict] = []
    seen: set[str] = set()
    text_parts: list[str] = []

    out = getattr(response, "output", None) or []
    for item in out:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            ptype = getattr(part, "type", None)
            if ptype != "output_text":
                continue
            chunk = getattr(part, "text", None) or ""
            if chunk:
                text_parts.append(chunk)
            for ann in getattr(part, "annotations", None) or []:
                atype = getattr(ann, "type", None)
                if atype != "url_citation":
                    continue
                url = (getattr(ann, "url", None) or "").strip()
                title = (getattr(ann, "title", None) or "").strip() or "Source"
                if url and url not in seen:
                    seen.add(url)
                    items.append({
                        "title": title,
                        "url": url,
                        "source": title,
                        "published": "",
                    })

    merged = getattr(response, "output_text", None)
    if merged and str(merged).strip():
        summary = str(merged).strip()
    else:
        summary = "\n\n".join(text_parts).strip()

    return summary, items[:limit]


def fetch_news_openai(merchant_name: str, limit: int = 8, legal_entity: str = ""):
    """
    OpenAI **Responses API** with the built-in **web_search** tool (live web + citations).
    Requires a recent `openai` Python package with `client.responses.create`.
    Returns (articles, summary_text, None) or (None, None, error).
    """
    client = get_openai_client()
    if not client:
        return None, None, MSG_NEWS_NOT_CONFIGURED

    if not hasattr(client, "responses") or not hasattr(client.responses, "create"):
        return None, None, (
            "Your OpenAI SDK is too old for Responses API + web search. "
            "Run: pip install -U 'openai>=1.55.0'"
        )

    le = legal_entity.strip()
    legal_block = (
        f"Legal / corporate name provided: **{le}**. Use web search to confirm and disambiguate.\n"
        if le
        else "Infer the registered legal entity or parent company behind the consumer-facing brand when possible.\n"
    )
    prompt = f"""You are a commercial intelligence assistant for Affirm's merchant success team. **Use web search** for current, verifiable information (prioritize the last 12–24 months).

**Merchant (operating brand):** {merchant_name}
{legal_block}

Answer in **Markdown** with these sections:

### 1. Executive summary
2–3 sentences on what matters most for this merchant right now for a BNPL partner.

### 2. Legal entity & corporate context
Parent company, legal name, public ticker if any (only if found via search).

### 3. Recent news & developments
Product, partnerships, leadership, funding, M&A, earnings, regulatory — with approximate dates where available.

### 4. Competitive & industry landscape
Competitors, category trends, external risks relevant to this merchant.

### 5. Actionable next steps for the CSM
4–6 **specific** bullets for what the CSM should do next with Affirm (timing, co-marketing, risk monitoring, education). Each bullet should be concrete.

If search finds little on the exact brand, say so clearly and still give vertical-relevant actions. Do not invent facts; cite what you found on the web."""

    model = os.environ.get("OPENAI_NEWS_MODEL", "gpt-4o").strip() or "gpt-4o"
    tools = [{"type": "web_search", "external_web_access": True}]

    def _call(tool_choice):
        return client.responses.create(
            model=model,
            input=prompt,
            tools=tools,
            tool_choice=tool_choice,
            max_output_tokens=4096,
        )

    try:
        try:
            resp = _call("required")
        except Exception as first:
            # Some accounts/models reject forced tools; retry with auto
            err_s = str(first).lower()
            if "tool" in err_s or "required" in err_s or "unsupported" in err_s:
                resp = _call("auto")
            else:
                raise

        summary, items = _openai_responses_text_and_citations(resp, limit)
        if not summary:
            return None, None, "OpenAI returned an empty response. Try a different OPENAI_NEWS_MODEL or check API errors."
        return items, summary, None
    except Exception as e:
        return None, None, str(e)


def _news_search_query(merchant_name: str, legal_entity: str = "") -> str:
    """Build a web-oriented search query (recent news + industry context)."""
    parts = [merchant_name, "news", "2024", "2025"]
    if legal_entity.strip():
        parts.insert(1, legal_entity.strip())
    else:
        parts.extend(["company", "industry", "competitors"])
    return " ".join(parts)


def fetch_news_newsapi(merchant_name: str, limit: int = 8, legal_entity: str = ""):
    """Fetch recent news using News API (newsapi.org)."""
    key = os.environ.get("NEWS_API_KEY")
    if not key:
        return None, "NEWS_API_KEY not set. Get a key at https://newsapi.org/"

    import urllib.parse
    import urllib.request
    q = urllib.parse.quote_plus(_news_search_query(merchant_name, legal_entity))
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


def fetch_news_serper(merchant_name: str, limit: int = 8, legal_entity: str = ""):
    """Fetch news/search results using Serper (serper.dev)."""
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        return None, "SERPER_API_KEY not set."

    import urllib.request
    q = _news_search_query(merchant_name, legal_entity)
    req = urllib.request.Request(
        "https://google.serper.dev/news",
        data=json.dumps({"q": q, "num": limit}).encode(),
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


def fetch_news_gemini(merchant_name: str, limit: int = 8, legal_entity: str = ""):
    """
    Live web: Gemini + Google Search grounding (preferred for current news).
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
    le = legal_entity.strip()
    legal_block = (
        f"The user provided legal / corporate name: **{le}**. Use search to confirm or refine.\n"
        if le
        else "Use Google Search to infer the registered legal entity / parent company behind the storefront brand when possible.\n"
    )
    prompt = f"""You are a commercial intelligence assistant for Affirm’s merchant success team. **Use Google Search** for CURRENT, verifiable information (prioritize the last 12–24 months).

**Merchant (operating brand):** {merchant_name}
{legal_block}

Produce a structured answer in **Markdown** with these sections:

### 1. Executive summary
2–3 sentences on what matters most for this merchant *right now* for a BNPL partner.

### 2. Legal entity & corporate context
Parent company, legal name, public ticker if any, and relationship to the consumer-facing brand (only if found in search).

### 3. Recent news & developments
Product, partnerships, leadership, funding, M&A, earnings, regulatory — with approximate dates where available.

### 4. Competitive & industry landscape
Main competitors, category trends, and external risks (regulatory, macro, reputation) that could affect the merchant or financing programs.

### 5. Actionable next steps for the CSM
4–6 **specific** bullets: what the CSM should do next with Affirm (e.g. promo timing, co-marketing, risk monitoring, merchant education). Each bullet should be concrete and justified by context above.

If search finds little on the exact brand, say so clearly and still give vertical-relevant actions. Do not invent facts; distinguish search-supported facts from general industry practice.

After your Markdown report, on its own line, list up to {limit} **source titles** you relied on from search (for citation transparency).
"""
    try:
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_NEWS_MODEL", "gemini-2.0-flash"),
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


def _load_rows_from_csv_full():
    """All engagement rows from bundled CSV (same shape as CSCC export)."""
    path = ROOT / "merchant_success_command_center.csv"
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(dict(r))
    return rows


def get_dashboard_data():
    """
    Engagement rows from Google Sheet (if GOOGLE_SHEET_ID) or local CSV; merge Snowflake KPIs when configured.
    Returns None if no sheet and no CSV.
    """
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if sheet_id:
        gid = os.environ.get("GOOGLE_SHEET_GID", "0").strip() or "0"
        names, merchant_to_owner, merchant_to_gmv, merchant_to_legal, err = read_merchants_from_google_sheet(sheet_id, gid)
        if err:
            raise ValueError(err)
        from CSCC import build_rows
        rows = build_rows(names, merchant_to_owner, merchant_to_gmv, merchant_to_legal)
    else:
        rows = _load_rows_from_csv_full()
        if not rows:
            return None

    try:
        from snowflake_kpis import attach_kpis_to_rows

        rows = attach_kpis_to_rows(rows)
    except Exception:
        pass
    return rows


@app.route("/api/data")
def api_data():
    """Dashboard rows: Google Sheet or bundled CSV, plus Snowflake KPI columns when env is set."""
    try:
        rows = get_dashboard_data()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if rows is None:
        return jsonify({"error": "No live data source configured"}), 404
    return jsonify(rows)


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
    legal_entity = request.args.get("legal_entity", "").strip()
    if not merchant:
        return jsonify({"error": "Missing merchant query"}), 400
    limit = min(15, max(1, int(request.args.get("limit", 8))))
    force = request.args.get("source", "").lower()

    def respond(out: dict, source: str):
        out["source"] = source
        return jsonify(out)

    # Forced OpenAI-only (debug: Responses API + web search)
    if force == "openai" and os.environ.get("OPENAI_API_KEY"):
        items, summary, err = fetch_news_openai(merchant, limit, legal_entity=legal_entity)
        if err:
            return jsonify({"error": err}), 500 if err != MSG_NEWS_NOT_CONFIGURED else 400
        return respond(
            {"merchant": merchant, "articles": items or [], "summary": summary or ""},
            "openai",
        )

    # 1) Gemini + Google Search (live web — avoids stale ~2023 model knowledge)
    if os.environ.get("GEMINI_API_KEY"):
        items, summary, err = fetch_news_gemini(merchant, limit, legal_entity=legal_entity)
        if not err:
            return respond(
                {"merchant": merchant, "articles": items or [], "summary": summary or ""},
                "gemini",
            )
        if err and "not set" not in err and "Install" not in err:
            return jsonify({"error": err}), 500

    # 2) Serper (Google News index)
    items, err = fetch_news_serper(merchant, limit, legal_entity=legal_entity)
    if not err and items:
        return respond({"merchant": merchant, "articles": items, "summary": ""}, "serper")

    # 3) News API
    items, err = fetch_news_newsapi(merchant, limit, legal_entity=legal_entity)
    if not err and items:
        return respond({"merchant": merchant, "articles": items, "summary": ""}, "newsapi")

    # 4) OpenAI Responses API + web_search (live web + citations)
    if os.environ.get("OPENAI_API_KEY"):
        items, summary, err = fetch_news_openai(merchant, limit, legal_entity=legal_entity)
        if not err:
            return respond(
                {"merchant": merchant, "articles": items or [], "summary": summary or ""},
                "openai",
            )
        if err != MSG_NEWS_NOT_CONFIGURED:
            return jsonify({"error": err}), 500

    return jsonify({"error": MSG_NEWS_NOT_CONFIGURED}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
