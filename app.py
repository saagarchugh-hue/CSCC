"""
Flask server for the Merchant Success Command Center dashboard.
Serves the dashboard and provides AI-backed API endpoints:
  - POST /api/generate-email — generate multiple themed email drafts (uses merchant context + optional news intel from the client)
  - GET  /api/news?merchant=... — fetch latest news about the merchant
  - POST /api/strategic-brief — six-step strategic prep + action summary (intake JSON; Gemini or OpenAI)

Secrets (pick one):
  • **Local:** put secrets in `.env` and/or `Keys.env` next to `app.py` (see `.env.example`). Both are gitignored; `Keys.env` overrides `.env` when both exist.
  • **Shell / hosting:** set the same names as environment variables.
  • **Prompts:** optional `prompts/*.txt` templates (`email_drafts`, `news_openai`, `news_gemini`, `strategic_1`…`strategic_7`). Placeholders are `{{name}}`. Override directory with `CSCC_PROMPTS_DIR`.

  OPENAI_API_KEY — email drafts + OpenAI news fallback + strategic brief (OpenAI path)
  GEMINI_API_KEY — preferred for "Latest news" (Gemini + Google Search) + strategic brief (Gemini path)
  OPENAI_NEWS_MODEL, OPENAI_EMAIL_MODEL, GEMINI_NEWS_MODEL — optional overrides
  NEWS_API_KEY, SERPER_API_KEY — optional news fallbacks
  GOOGLE_SHEET_ID, GOOGLE_SHEET_GID — optional live sheet (see HOSTING.md)

Run: python app.py  (or: flask run --host=0.0.0.0)
Then open http://<this-machine-ip>:5000 for team access.
"""
import csv
import io
import json
import os
import re
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")

# Paths
ROOT = Path(__file__).resolve().parent
DASHBOARD_HTML = ROOT / "dashboard.html"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    # Optional: Keys.env (same variable names; loaded second so it overrides .env)
    load_dotenv(ROOT / "Keys.env", override=True)
except ImportError:
    pass


def _prompts_dir() -> Path:
    d = os.environ.get("CSCC_PROMPTS_DIR", "").strip()
    if d:
        return Path(d).expanduser()
    return ROOT / "prompts"


def render_prompt_file(name: str, **kwargs: str) -> str:
    """
    Load prompts/<name>.txt and replace {{key}} placeholders with kwargs values.
    Use for Generate email, Latest news (Gemini / OpenAI), so copy can be edited without changing Python.
    """
    path = _prompts_dir() / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file missing: {path}. Add it or set CSCC_PROMPTS_DIR to a folder containing {name}.txt"
        )
    text = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


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
MSG_STRATEGIC_NOT_CONFIGURED = "Strategic brief is not configured. Add GEMINI_API_KEY or OPENAI_API_KEY."


def _format_articles_for_prompt(articles: list | None) -> str:
    lines = []
    for a in (articles or [])[:12]:
        if not isinstance(a, dict):
            continue
        t = (a.get("title") or "").strip()
        u = (a.get("url") or "").strip()
        if t:
            lines.append(f"- {t}" + (f" ({u})" if u else ""))
    return "\n".join(lines) if lines else "(none)"


def _parse_email_drafts_json(raw: str) -> tuple[list[dict] | None, str | None]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Could not parse model response as JSON: {e}"
    drafts = obj.get("drafts")
    if not isinstance(drafts, list):
        return None, "Response missing drafts array"
    out: list[dict] = []
    for d in drafts:
        if not isinstance(d, dict):
            continue
        theme = str(d.get("theme", "Draft")).strip() or "Draft"
        body = str(d.get("body", "")).strip()
        if body:
            out.append({"theme": theme, "body": body})
    if not out:
        return None, "No non-empty draft bodies in response"
    return out, None


def generate_email_drafts_via_openai(payload: dict) -> tuple[list[dict] | None, bool | None, str | None]:
    """
    Return (drafts, news_was_used, error). Each draft: {"theme": str, "body": str}.
    Client should POST news_summary / news_articles / news_source from the same /api/news flow
    used by “Latest news” so drafts align with that intelligence.
    """
    client = get_openai_client()
    if not client:
        return None, None, MSG_EMAIL_NOT_CONFIGURED

    merchant = payload.get("merchant", "") or ""
    vertical = payload.get("vertical", "")
    tier = payload.get("tier", "")
    engagement_month = payload.get("engagement_month_label", "")
    engagement_type = payload.get("engagement_type", "")
    playbook = payload.get("playbook", "")
    peak_months = payload.get("peak_months", "")
    next_action = payload.get("next_action", "")
    owner = payload.get("owner", "")
    fy26_gmv = payload.get("fy26_fc_gmv", "")

    news_summary = (payload.get("news_summary") or "").strip()
    news_articles = payload.get("news_articles") or []
    if not isinstance(news_articles, list):
        news_articles = []
    news_source = (payload.get("news_source") or "").strip()

    news_used = bool(news_summary or news_articles)
    headlines_block = _format_articles_for_prompt(news_articles)

    gmv_line = f"- FY26 FC GMV with Affirm (forecast / plan): {fy26_gmv}.\n" if str(fy26_gmv).strip() else ""

    intel_block = f"""**Merchant intelligence** (output from the same “Latest news” style research the CSM can open in the dashboard; may include executive summary, legal context, news, competitive/industry, and **actionable next steps for the CSM**):
- Source label: {news_source or "(not provided)"}
- Summary / analysis (often Markdown; treat recommendations as guidance, not as facts the merchant has confirmed):
{news_summary if news_summary else "(No brief was supplied—generate drafts from merchant context only; do not invent current events.)"}
- Headlines / citations (if any):
{headlines_block}
"""

    prompt = render_prompt_file(
        "email_drafts",
        merchant=merchant,
        vertical=vertical,
        tier=tier,
        engagement_month=engagement_month,
        engagement_type=engagement_type,
        peak_months=peak_months,
        playbook=playbook,
        next_action=next_action,
        owner=owner,
        gmv_line=gmv_line,
        intel_block=intel_block,
    )

    model = os.environ.get("OPENAI_EMAIL_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=4096,
        )
        raw = (resp.choices[0].message.content or "").strip()
        drafts, perr = _parse_email_drafts_json(raw)
        if perr:
            return None, news_used, perr
        return drafts, news_used, None
    except Exception as e:
        return None, news_used, str(e)


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
    prompt = render_prompt_file(
        "news_openai",
        merchant_name=merchant_name,
        legal_block=legal_block,
    )

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
    prompt = render_prompt_file(
        "news_gemini",
        merchant_name=merchant_name,
        legal_block=legal_block,
        limit=str(limit),
    )
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


def _truncate_chain(text: str, max_chars: int = 14000) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 80].rstrip() + "\n\n[…truncated for downstream prompts…]"


def _am_optional_block(note: str) -> str:
    n = (note or "").strip()
    if not n:
        return ""
    return "\n\n---\n**Additional context from the Account Manager:**\n" + n


def _gemini_strategic_generate(prompt: str, use_search: bool) -> tuple[str | None, str | None]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, MSG_STRATEGIC_NOT_CONFIGURED
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None, "Install the Gemini SDK: pip install google-genai"

    client = genai.Client(api_key=key)
    model = os.environ.get("GEMINI_STRATEGIC_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    if use_search:
        config = types.GenerateContentConfig(
            max_output_tokens=8192,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    else:
        config = types.GenerateContentConfig(max_output_tokens=8192)
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        return None, str(e)
    if not response.candidates:
        return None, "No response from Gemini"
    return (response.text or "").strip() or None, None


def _openai_strategic_web(prompt: str) -> tuple[str | None, str | None]:
    """Step 1: Responses API + web_search for current public facts."""
    client = get_openai_client()
    if not client:
        return None, MSG_STRATEGIC_NOT_CONFIGURED
    if not hasattr(client, "responses") or not hasattr(client.responses, "create"):
        return None, (
            "Your OpenAI SDK is too old for Responses API + web search. "
            "Run: pip install -U 'openai>=1.55.0'"
        )
    model = os.environ.get("OPENAI_STRATEGIC_MODEL", "gpt-4o").strip() or "gpt-4o"
    tools = [{"type": "web_search", "external_web_access": True}]

    def _call(tool_choice):
        return client.responses.create(
            model=model,
            input=prompt,
            tools=tools,
            tool_choice=tool_choice,
            max_output_tokens=8192,
        )

    try:
        try:
            resp = _call("required")
        except Exception as first:
            err_s = str(first).lower()
            if "tool" in err_s or "required" in err_s or "unsupported" in err_s:
                resp = _call("auto")
            else:
                raise
        summary, _items = _openai_responses_text_and_citations(resp, 20)
        if not summary:
            return None, "OpenAI returned an empty response for strategic step 1."
        return summary.strip(), None
    except Exception as e:
        return None, str(e)


def _openai_strategic_chat(prompt: str) -> tuple[str | None, str | None]:
    client = get_openai_client()
    if not client:
        return None, MSG_STRATEGIC_NOT_CONFIGURED
    model = os.environ.get("OPENAI_STRATEGIC_MODEL", "gpt-4o").strip() or "gpt-4o"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return raw or None, None
    except Exception as e:
        return None, str(e)


def run_strategic_brief(payload: dict) -> dict:
    """
    Run prompts strategic_1 … strategic_7. Step 1 uses live web (Gemini Google Search or OpenAI web_search).
    Returns dict with provider, steps (each id, title, content, error), action_summary, error (top-level if any).
    """
    company_name = (payload.get("company_name") or "").strip()
    if not company_name:
        return {"error": "Missing company_name", "provider": "", "steps": [], "action_summary": ""}

    industry = (payload.get("industry") or "").strip()
    business_model = (payload.get("business_model") or "").strip()
    products_services = (payload.get("products_services") or "").strip()
    geography = (payload.get("geography") or "").strip()
    known_partners = (payload.get("known_partners") or "").strip()
    target_persona = (payload.get("target_persona") or "").strip()
    additional = (payload.get("additional_context") or "").strip()

    prov = (payload.get("provider") or "").strip().lower()
    if prov not in ("gemini", "openai", ""):
        prov = ""
    if not prov:
        prov = "gemini" if os.environ.get("GEMINI_API_KEY") else "openai"

    if prov == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        return {"error": "GEMINI_API_KEY not set (required for provider=gemini).", "provider": prov, "steps": [], "action_summary": ""}
    if prov == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return {"error": "OPENAI_API_KEY not set (required for provider=openai).", "provider": prov, "steps": [], "action_summary": ""}

    steps_meta = [
        ("company_context", "1. Company context"),
        ("persona_problems", "2. Persona problems"),
        ("current_state", "3. Current state"),
        ("cost_of_inaction", "4. Cost of inaction"),
        ("discovery_hooks", "5. Discovery hooks"),
        ("partner_reframe", "6. Partner reframe"),
        ("action_summary", "7. Action summary"),
    ]
    steps_out: list[dict] = []

    def add_step(sid: str, title: str, content: str, err: str | None):
        steps_out.append({"id": sid, "title": title, "content": content or "", "error": err})

    am = _am_optional_block(additional)

    # --- Step 1
    try:
        p1 = render_prompt_file(
            "strategic_1_company_context",
            company_name=company_name,
            industry=industry or "—",
            business_model=business_model or "—",
            products_services=products_services or "—",
            geography=geography or "—",
            known_partners=known_partners or "—",
            target_persona=target_persona or "—",
        ) + am
    except FileNotFoundError as e:
        return {"error": str(e), "provider": prov, "steps": [], "action_summary": ""}

    if prov == "gemini":
        s1, e1 = _gemini_strategic_generate(p1, use_search=True)
    else:
        s1, e1 = _openai_strategic_web(p1)

    if e1 or not s1:
        add_step("company_context", steps_meta[0][1], "", e1 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}

    add_step("company_context", steps_meta[0][1], s1, None)
    strategy_summary = _truncate_chain(s1)

    # --- Step 2
    p2 = render_prompt_file(
        "strategic_2_persona_problems",
        company_name=company_name,
        target_persona=target_persona or "—",
        strategy_summary=strategy_summary,
        known_partners=known_partners or "—",
    ) + am
    if prov == "gemini":
        s2, e2 = _gemini_strategic_generate(p2, use_search=False)
    else:
        s2, e2 = _openai_strategic_chat(p2)
    if e2 or not s2:
        add_step("persona_problems", steps_meta[1][1], "", e2 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("persona_problems", steps_meta[1][1], s2, None)
    problems_summary = _truncate_chain(s2)

    # --- Step 3
    p3 = render_prompt_file(
        "strategic_3_current_state",
        company_name=company_name,
        target_persona=target_persona or "—",
        known_partners=known_partners or "—",
        problems_summary=problems_summary,
    ) + am
    if prov == "gemini":
        s3, e3 = _gemini_strategic_generate(p3, use_search=False)
    else:
        s3, e3 = _openai_strategic_chat(p3)
    if e3 or not s3:
        add_step("current_state", steps_meta[2][1], "", e3 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("current_state", steps_meta[2][1], s3, None)
    current_state_summary = _truncate_chain(s3)

    # --- Step 4
    p4 = render_prompt_file(
        "strategic_4_cost_of_inaction",
        company_name=company_name,
        target_persona=target_persona or "—",
        current_state_summary=current_state_summary,
        strategy_summary=strategy_summary,
        known_partners=known_partners or "—",
    ) + am
    if prov == "gemini":
        s4, e4 = _gemini_strategic_generate(p4, use_search=False)
    else:
        s4, e4 = _openai_strategic_chat(p4)
    if e4 or not s4:
        add_step("cost_of_inaction", steps_meta[3][1], "", e4 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("cost_of_inaction", steps_meta[3][1], s4, None)
    cost_of_inaction_summary = _truncate_chain(s4)

    # --- Step 5
    p5 = render_prompt_file(
        "strategic_5_discovery_hooks",
        company_name=company_name,
        target_persona=target_persona or "—",
        strategy_summary=strategy_summary,
        problems_summary=problems_summary,
        current_state_summary=current_state_summary,
        cost_of_inaction_summary=cost_of_inaction_summary,
    ) + am
    if prov == "gemini":
        s5, e5 = _gemini_strategic_generate(p5, use_search=False)
    else:
        s5, e5 = _openai_strategic_chat(p5)
    if e5 or not s5:
        add_step("discovery_hooks", steps_meta[4][1], "", e5 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("discovery_hooks", steps_meta[4][1], s5, None)

    # --- Step 6
    p6 = render_prompt_file(
        "strategic_6_partner_reframe",
        known_partners=known_partners or "—",
        strategy_summary=strategy_summary,
        cost_of_inaction_summary=cost_of_inaction_summary,
    ) + am
    if prov == "gemini":
        s6, e6 = _gemini_strategic_generate(p6, use_search=False)
    else:
        s6, e6 = _openai_strategic_chat(p6)
    if e6 or not s6:
        add_step("partner_reframe", steps_meta[5][1], "", e6 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("partner_reframe", steps_meta[5][1], s6, None)

    # --- Step 7 (synthesis)
    p7 = render_prompt_file(
        "strategic_7_action_summary",
        s1=_truncate_chain(s1, 6000),
        s2=_truncate_chain(s2, 6000),
        s3=_truncate_chain(s3, 6000),
        s4=_truncate_chain(s4, 6000),
        s5=_truncate_chain(s5, 6000),
        s6=_truncate_chain(s6, 6000),
    )
    if prov == "gemini":
        s7, e7 = _gemini_strategic_generate(p7, use_search=False)
    else:
        s7, e7 = _openai_strategic_chat(p7)
    if e7 or not s7:
        add_step("action_summary", steps_meta[6][1], "", e7 or "Empty response")
        return {"error": None, "provider": prov, "steps": steps_out, "action_summary": ""}
    add_step("action_summary", steps_meta[6][1], s7, None)

    return {"error": None, "provider": prov, "steps": steps_out, "action_summary": s7 or ""}


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
    drafts, news_used, err = generate_email_drafts_via_openai(payload)
    if err:
        is_not_configured = err == MSG_EMAIL_NOT_CONFIGURED
        return jsonify({"error": err}), 400 if is_not_configured else 500
    return jsonify({"drafts": drafts, "news_used": bool(news_used)})


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


@app.route("/api/strategic-brief", methods=["POST"])
def api_strategic_brief():
    try:
        payload = request.get_json() or {}
    except Exception:
        payload = {}
    out = run_strategic_brief(payload)
    err = out.get("error")
    if err:
        low = err.lower()
        code = 400 if "missing" in low or "not set" in low or "requires" in low else 500
        return jsonify(out), code
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
