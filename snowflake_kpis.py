"""
Optional Snowflake metrics merged into merchant dashboard rows.

Uses the same account as typical Affirm setups (see setup_mcp.sh). The Cursor
Snowflake MCP does NOT call this — your Flask app needs its own connection.

Environment variables (when unset, KPI fetch is skipped):
  SNOWFLAKE_ACCOUNT     e.g. AFFIRM-AFFIRMUSEAST
  SNOWFLAKE_USER        e.g. you@affirm.com
  SNOWFLAKE_AUTHENTICATOR  externalbrowser (local) | oauth | etc.
  SNOWFLAKE_WAREHOUSE   optional
  SNOWFLAKE_ROLE        optional
  SNOWFLAKE_DATABASE    optional
  SNOWFLAKE_SCHEMA      optional
  SNOWFLAKE_KPI_SQL_PATH  optional path to SQL file (default: sql/merchant_kpis.sql)
  The SQL file must contain {MERCHANT_IN} which is replaced with quoted literals.

For headless deploy (Railway), use key-pair or OAuth token auth — not externalbrowser.
See: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

KPI_KEYS = (
    "num_applications",
    "approval_rate",
    "take_rate",
    "loans",
    "aov",
)


def _sql_escape_literal(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _merchant_in_clause(merchant_names: list[str]) -> str:
    return ", ".join(_sql_escape_literal(n) for n in merchant_names if n)


def load_kpi_sql() -> str:
    path = os.environ.get("SNOWFLAKE_KPI_SQL_PATH") or str(ROOT / "sql" / "merchant_kpis.sql")
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def fetch_merchant_kpis(merchant_names: list[str]) -> dict[str, dict]:
    """
    Returns dict keyed by normalized merchant name (lower) -> KPI fields.
    Empty dict if Snowflake not configured, query missing, or error (logs to stderr).
    """
    if not merchant_names:
        return {}
    account = os.environ.get("SNOWFLAKE_ACCOUNT", "").strip()
    user = os.environ.get("SNOWFLAKE_USER", "").strip()
    if not account or not user:
        return {}

    sql_template = load_kpi_sql()
    if "{MERCHANT_IN}" not in sql_template:
        import sys
        print("snowflake_kpis: SQL must include {MERCHANT_IN} placeholder.", file=sys.stderr)
        return {}

    merchant_in = _merchant_in_clause(merchant_names)
    if not merchant_in:
        return {}

    sql = sql_template.replace("{MERCHANT_IN}", merchant_in)

    try:
        import snowflake.connector
    except ImportError:
        import sys
        print("snowflake_kpis: pip install snowflake-connector-python", file=sys.stderr)
        return {}

    conn_kwargs = {
        "account": account,
        "user": user,
        "authenticator": os.environ.get("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
    }
    wh = os.environ.get("SNOWFLAKE_WAREHOUSE")
    role = os.environ.get("SNOWFLAKE_ROLE")
    database = os.environ.get("SNOWFLAKE_DATABASE")
    schema = os.environ.get("SNOWFLAKE_SCHEMA")
    if wh:
        conn_kwargs["warehouse"] = wh
    if role:
        conn_kwargs["role"] = role
    if database:
        conn_kwargs["database"] = database
    if schema:
        conn_kwargs["schema"] = schema

    # Private key auth (headless)
    pk_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", "").strip()
    if pk_path:
        from pathlib import Path as P
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        conn_kwargs.pop("authenticator", None)
        with open(P(pk_path), "rb") as key:
            p_key = serialization.load_pem_private_key(key.read(), password=None, backend=default_backend())
        pkb = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        conn_kwargs["private_key"] = pkb

    out: dict[str, dict] = {}
    try:
        conn = snowflake.connector.connect(**conn_kwargs)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            cols = [c[0].lower() for c in cur.description] if cur.description else []
            for row in cur.fetchall() or []:
                if not row:
                    continue
                rec = {cols[i]: row[i] for i in range(len(cols))}
                raw_name = (
                    rec.get("merchant_name")
                    or rec.get("merchant")
                    or rec.get("merchant_display_name")
                    or rec.get("name")
                )
                if raw_name is None:
                    continue
                key = " ".join(str(raw_name).strip().split()).lower()
                mapped = {
                    "num_applications": rec.get("num_applications") or rec.get("applications") or rec.get("app_count"),
                    "approval_rate": rec.get("approval_rate") or rec.get("approval_rate_pct"),
                    "take_rate": rec.get("take_rate") or rec.get("take_rate_pct"),
                    "loans": rec.get("loans") or rec.get("loan_count") or rec.get("num_loans"),
                    "aov": rec.get("aov") or rec.get("aov_usd") or rec.get("avg_order_value"),
                }
                out[key] = {k: mapped.get(k) for k in KPI_KEYS}
        finally:
            conn.close()
    except Exception as e:
        import sys
        print(f"snowflake_kpis: {e}", file=sys.stderr)
        return {}

    return out


def merge_kpis_into_rows(rows: list[dict], kpis: dict[str, dict]) -> list[dict]:
    """Attach KPI columns to each row (same merchant gets same KPIs on every engagement row)."""
    if not kpis:
        for r in rows:
            for k in KPI_KEYS:
                r[k] = ""
        return rows

    for r in rows:
        name = " ".join(str(r.get("merchant", "")).strip().split())
        key = name.lower()
        m = kpis.get(key)
        if not m:
            for alt in kpis:
                if alt == key or name.lower() == alt:
                    m = kpis[alt]
                    break
        if not m:
            for k in KPI_KEYS:
                r[k] = ""
            continue
        for k in KPI_KEYS:
            v = m.get(k)
            if v is None or v == "":
                r[k] = ""
            elif k in ("approval_rate", "take_rate") and isinstance(v, (int, float)):
                x = float(v)
                r[k] = f"{x * 100:.1f}%" if 0 <= x <= 1 else f"{x:.1f}%"
            elif k == "aov" and isinstance(v, (int, float)):
                r[k] = f"${float(v):,.2f}"
            else:
                r[k] = str(v)
    return rows


def attach_kpis_to_rows(rows: list[dict]) -> list[dict]:
    """Fetch KPIs for distinct merchants in rows and merge."""
    names = []
    seen = set()
    for r in rows:
        m = r.get("merchant", "")
        if m and m not in seen:
            seen.add(m)
            names.append(m)
    kpis = fetch_merchant_kpis(names)
    return merge_kpis_into_rows(rows, kpis)
