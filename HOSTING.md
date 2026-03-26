# Hosting the Merchant Success Command Center for Affirm

So everyone at Affirm can access the dashboard, you can host it in one of these ways.

---

## Can the dashboard be hosted on Notion?

**Notion cannot host this dashboard as a native page.** Notion doesn’t run custom HTML/JavaScript apps. You have two practical options:

1. **Embed the dashboard in Notion**  
   Host the dashboard somewhere else (internal server, Railway, Render, etc.) so it has a **public or internal URL**. Then in a Notion page, use **Embed** (type `/embed` or use the “…” menu → Embed) and paste that URL. Notion will show it in an iframe.  
   - The URL must be reachable from the browser (e.g. `https://your-dashboard.railway.app` or `http://your-internal-server:5000` if your network allows).  
   - Some Notion setups restrict which domains can be embedded; if the embed is blocked, your admin may need to allow the domain or you’ll need to use a link instead of an embed.

2. **Use Notion only as a link**  
   Put the dashboard URL in a Notion page as a normal link. People click through to open the full dashboard in a new tab. No embed, but no Notion restrictions.

So: **host the app elsewhere, then either embed that URL in Notion or link to it from Notion.**

---

## Deploy without API keys (for testing / pitching)

You can deploy the app **with no API keys set**. The dashboard loads, filters and search work, and the table is fully usable. The “Generate email” and “Latest news” buttons will show a short message: *“Email generation is not configured for this deployment…”* and *“Latest news is not configured for this deployment…”*. Add API keys later when you’re ready to enable those features.

**Steps:**

1. **Build the dashboard once** (on your machine, where the Excel/CSV lives):
   ```bash
   python build_dashboard.py
   ```
   Commit `dashboard.html` (and optionally `merchant_success_command_center.csv` if you don’t commit the Excel) so the deployed app has data.

2. **Push to GitHub** (or GitLab, etc.).

3. **Deploy to Render or Railway** (no env vars required):
   - **Render:** New → Web Service → connect repo. Build: `pip install -r requirements.txt`. Start: `python app.py`. Leave “Environment” empty.
   - **Railway:** New project → Deploy from repo. It will use the `Procfile` (`web: python app.py`). No variables needed.
   - Both use the `PORT` env var automatically; the app already reads it.

4. Open the generated URL. Use the dashboard; when you click “Generate email” or “Latest news”, you’ll see the friendly “not configured” message until you add the corresponding API keys in the host’s environment.

**Deploy from your machine (Railway CLI):**

1. Install the CLI once: `npm install -g @railway/cli`
2. Log in (opens browser): `railway login`
3. Link a project (once): `railway init --name cscc-dashboard`
4. Deploy: `./deploy.sh` (or `railway up`)
5. Railway will print your live URL; or run `railway open` to open it.

**If you see `invalid peer certificate: UnknownIssuer` (Railway CLI):**

This usually means your network (e.g. corporate proxy or VPN) is intercepting HTTPS, so the CLI can’t verify Railway’s certificate. **Use the GitHub + Railway dashboard flow instead** (no CLI on your machine):

1. **Create a new repo on GitHub:** github.com → **New repository** → name it (e.g. `cscc-dashboard`) → **Create repository**. Do not add a README or .gitignore (you already have code).
2. **Copy the repo URL** GitHub shows (e.g. `https://github.com/your-username/cscc-dashboard.git`).
3. **In this project folder, add the remote and push** (use your actual URL from step 2):
   ```bash
   git remote remove origin   # only if you already added a wrong URL
   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```
   Replace `YOUR_GITHUB_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and the repo name you created.
4. Go to [railway.app](https://railway.app) and sign in with GitHub.
5. **New Project** → **Deploy from GitHub repo** → choose your repo.
6. Railway will detect the `Procfile` and deploy. In the project: **Settings** → **Networking** → **Generate domain** to get your dashboard URL.

Same result as the CLI; only the connection to Railway goes through the browser instead of the terminal.

---

## Option 1: Internal server / VM (recommended for “everyone at Affirm”)

Run the Flask app on a machine that’s reachable on your internal network (e.g. a shared VM or server).

1. **On the server**
   - Clone or copy this project.
   - Install dependencies: `pip install -r requirements.txt` (or use the project’s `.venv`).
   - Set API keys (for AI features):
     - `OPENAI_API_KEY` – required for “Generate email”.
     - `GEMINI_API_KEY` – optional; for “Latest news” via Gemini + Google Search (recommended).
     - `NEWS_API_KEY` and/or `SERPER_API_KEY` – optional fallbacks for “Latest news” (see [app.py](app.py) and [API keys](#api-keys) below).
   - Build the dashboard once: `python build_dashboard.py`.
   - Start the app:
     ```bash
     flask run --host=0.0.0.0 --port=5000
     ```
     Or: `python app.py`

2. **Share the URL**
   - From other machines on the same network: `http://<server-ip>:5000`
   - Example: `http://10.0.1.50:5000` (use your server’s real IP or hostname).

3. **Optional**
   - Run behind a reverse proxy (e.g. nginx) with HTTPS and/or SSO if your company uses it.
   - Use a process manager (systemd, supervisord) or a production WSGI server (e.g. `gunicorn`) so it stays up after you log out.

---

## Option 2: Cloud deployment (Railway, Render, Fly.io, etc.)

Deploy the Flask app so it’s reachable via a public URL (you can still restrict access with auth or VPN).

1. **Prepare**
   - Ensure `dashboard.html` is generated and committed (or generated in the deploy step).
   - In the cloud dashboard, set:
     - `OPENAI_API_KEY`
     - `NEWS_API_KEY` and/or `SERPER_API_KEY` (optional)

2. **Example: Railway / Render**
   - Connect the repo; set build command to `pip install -r requirements.txt` and run `python build_dashboard.py` if you generate the HTML at deploy time.
   - Start command: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app` (or `flask run --host=0.0.0.0` if the platform sets `PORT`).
   - Share the generated URL (e.g. `https://your-app.railway.app`) with the team.

3. **Access control**
   - Add HTTP basic auth, or put the app behind your company’s SSO/proxy so only Affirm users can access it.

---

## Option 3: Static dashboard only (no AI features)

If you don’t need “Generate email” or “Latest news” on the server:

1. Run `python build_dashboard.py` to generate `dashboard.html`.
2. Host that single file:
   - **Internal:** Put `dashboard.html` on a shared drive or internal site (e.g. Confluence, SharePoint, or any internal static host). People open the file or link; filters and search work, but the two buttons will show “Run the Flask server for AI features” unless they point to your server.
   - **With AI:** Serve the same file from the Flask app (Option 1 or 2) so the buttons work for everyone.

---

## Live data from a Google Sheet

The dashboard can load merchant data from a **published** Google Sheet instead of the embedded snapshot. When you set the variables below, the app fetches the sheet on each page load and builds the table from it.

**1. Publish the sheet to web (required)**

- Open your Google Sheet (e.g. [this one](https://docs.google.com/spreadsheets/d/1Hnn57sIcoLuotdJrXkx5TLxT1efCWFx_s_CJFtsKeKo/edit?gid=943969620#gid=943969620)).
- **File** → **Share** → **Publish to web** (or **File** → **Share** → **Publish to web**).
- Choose the correct **sheet/tab** (e.g. the one with gid `943969620`).
- Set format to **Comma-separated values (.csv)** → **Publish**.  
  Anyone with the link can view the CSV; the dashboard only reads it, it does not edit.

**2. Set environment variables**

From the sheet URL  
`https://docs.google.com/spreadsheets/d/ **SHEET_ID** /edit?gid= **GID**`  
use:

- **GOOGLE_SHEET_ID** = `1Hnn57sIcoLuotdJrXkx5TLxT1efCWFx_s_CJFtsKeKo` (the long id after `/d/`).
- **GOOGLE_SHEET_GID** = `943969620` (the number after `gid=`). Omit or set to `0` to use the first sheet.

Example (Railway): **Variables** → add `GOOGLE_SHEET_ID` and `GOOGLE_SHEET_GID` → redeploy.

**3. Sheet format**

- First row = headers. The app looks for **Account** / merchant / name, **CSM** (or Owner), and optionally **FY26 FC GMV** (or any header containing `gmv`, `fy26`, or `fc gmv`).
- Same idea as the Excel managed-merchants file: one row per merchant; **FY26 FC GMV** is shown on the dashboard and used in generated emails when present.

If the sheet is private or not published, the dashboard falls back to the data embedded in `dashboard.html` (from the last time you ran `python build_dashboard.py`).

---

## Snowflake: loan / application KPIs (apps, approval %, take rate, loans, AOV)

**Cursor’s Snowflake MCP** only helps *you* query Snowflake from the editor. The **hosted dashboard** does **not** use MCP; it runs SQL via `snowflake-connector-python` when you configure the environment.

1. **Edit the SQL** in `sql/merchant_kpis.sql` so it selects from **your** Affirm tables. The query must return columns (aliases) including:
   - `merchant_name` (must match merchant names in the managed-merchant list)
   - `num_applications`, `approval_rate`, `take_rate`, `loans`, `aov`  
   The file must contain `{MERCHANT_IN}` — the app replaces it with a quoted `IN (...)` list.

2. **Set env vars** (local or Railway), for example:
   - `SNOWFLAKE_ACCOUNT` = e.g. `AFFIRM-AFFIRMUSEAST`
   - `SNOWFLAKE_USER` = your `@affirm.com` user
   - `SNOWFLAKE_AUTHENTICATOR` = `externalbrowser` (local SSO) or use **key-pair** for headless deploy (see Snowflake docs)
   - Optional: `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`
   - Optional: `SNOWFLAKE_KPI_SQL_PATH` = absolute path to a custom SQL file
   - For servers: `SNOWFLAKE_PRIVATE_KEY_PATH` + key-pair auth (no browser)

3. **Install deps:** `pip install -r requirements.txt` (includes `snowflake-connector-python`).

4. **Redeploy** after changing SQL or env vars.

The dashboard adds columns **Apps**, **Approval %**, **Take rate %**, **Loans**, **AOV** and fills them from this query. If Snowflake is not configured or the query returns no row for a merchant, those cells stay empty.

---

## API keys (for AI features)

- **OPENAI_API_KEY** – Powers **both** “Generate email” and “Latest news”. Create an API key in the [OpenAI dashboard](https://platform.openai.com/api-keys). When set, email uses it for reach-out text and news uses it for a summary about the merchant (no separate news API needed).  
  **Where to set:** Railway → your project → **Variables** → Add variable `OPENAI_API_KEY` = your key (exact name). After adding or changing variables, **trigger a redeploy** (e.g. Deployments → ⋮ → Redeploy) so the app sees the new value. Never commit the key to git.
- **GEMINI_API_KEY** – Optional; “Latest news” can use **Gemini + Google Search** instead of (or after) OpenAI. Get a key at [Google AI Studio](https://aistudio.google.com/apikey). When set and OpenAI is not set, the news button uses Gemini.
- **NEWS_API_KEY** – Optional; fallback for “Latest news”. Free tier at [newsapi.org](https://newsapi.org/).
- **SERPER_API_KEY** – Optional; alternative fallback for “Latest news” (Google search via [serper.dev](https://serper.dev)).

If no keys are set, the dashboard still loads; the email and news buttons show a “not configured” message.

---

## Quick checklist for “everyone at Affirm”

- [ ] Run `python build_dashboard.py` to create `dashboard.html`.
- [ ] Run the Flask app with `flask run --host=0.0.0.0` (or deploy to a cloud host).
- [ ] Set `OPENAI_API_KEY` (and optionally news keys) where the app runs.
- [ ] Share the URL (e.g. `http://<internal-server>:5000` or your cloud URL).
- [ ] (Optional) Add auth or put the app behind company SSO for access control.
