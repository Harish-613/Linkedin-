"""Postgres access: schema setup, company entity resolution and upserts."""

import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from lpp.normalize import classify_title, normalize_company, normalize_domain

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def connect(dsn: str | None = None) -> psycopg.Connection:
    dsn = dsn or os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/linkedinpp")
    return psycopg.connect(dsn, autocommit=False)


def init_schema(conn) -> None:
    conn.execute(SCHEMA.read_text())
    conn.commit()


# ---------------------------------------------------------------- companies

def find_company(conn, name: str | None = None, domain: str | None = None, cik: int | None = None) -> int | None:
    """Most reliable identifier first: CIK, then website domain, then any known name."""
    if cik is not None:
        row = conn.execute("SELECT id FROM companies WHERE cik = %s", (cik,)).fetchone()
        if row:
            return row[0]
    d = normalize_domain(domain)
    if d:
        row = conn.execute("SELECT id FROM companies WHERE domain = %s", (d,)).fetchone()
        if row:
            return row[0]
    if name:
        row = conn.execute("SELECT company_id FROM company_aliases WHERE alias = %s",
                           (normalize_company(name),)).fetchone()
        if row:
            return row[0]
    return None


def upsert_company(conn, name: str, domain: str | None = None, cik: int | None = None,
                   ticker: str | None = None, aliases: list[str] = (), **fields) -> int:
    """Find-or-create, filling in identifiers the existing row is missing.

    fields: crunchbase_permalink, ats_provider, ats_token.
    """
    d = normalize_domain(domain)
    cid = find_company(conn, name, d, cik)
    for alias in aliases:  # e.g. seed "Google" with alias "Alphabet" joins SEC's Alphabet Inc.
        if cid is None and alias:
            cid = find_company(conn, name=alias)
    if cid is None:
        cid = conn.execute(
            "INSERT INTO companies (name, normalized_name, domain, cik, ticker) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (name, normalize_company(name), d, cik, ticker)).fetchone()[0]
    else:
        conn.execute(
            """UPDATE companies SET
                 domain = COALESCE(domain, %s), cik = COALESCE(cik, %s), ticker = COALESCE(ticker, %s),
                 updated_at = now()
               WHERE id = %s""", (d, cik, ticker, cid))
    for key in ("crunchbase_permalink", "ats_provider", "ats_token"):
        if fields.get(key):
            conn.execute(f"UPDATE companies SET {key} = %s WHERE id = %s", (fields[key], cid))
    for alias in {name, ticker, *aliases} - {None, ""}:
        add_alias(conn, cid, alias)
    return cid


def add_alias(conn, company_id: int, alias: str) -> None:
    norm = normalize_company(alias)
    if norm:
        conn.execute("INSERT INTO company_aliases (alias, company_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (norm, company_id))


# ---------------------------------------------------------------- per-source writes

def save_sec(conn, company_id: int, info: dict) -> None:
    conn.execute(
        """INSERT INTO sec_financials (company_id, fiscal_year, revenue_usd, net_income_usd, revenue_growth,
                                       sic_description, state, fetched_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (company_id) DO UPDATE SET
             fiscal_year = EXCLUDED.fiscal_year, revenue_usd = EXCLUDED.revenue_usd,
             net_income_usd = EXCLUDED.net_income_usd, revenue_growth = EXCLUDED.revenue_growth,
             sic_description = EXCLUDED.sic_description, state = EXCLUDED.state, fetched_at = now()""",
        (company_id, info.get("fiscal_year"), info.get("revenue_usd"), info.get("net_income_usd"),
         info.get("revenue_growth"), info.get("sic_description"), info.get("state")))


def save_funding(conn, company_id: int, org: dict) -> None:
    conn.execute(
        """INSERT INTO funding (company_id, total_usd, last_round_type, founded_on, employee_min, employee_max,
                                categories, fetched_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (company_id) DO UPDATE SET
             total_usd = EXCLUDED.total_usd, last_round_type = EXCLUDED.last_round_type,
             founded_on = EXCLUDED.founded_on, employee_min = EXCLUDED.employee_min,
             employee_max = EXCLUDED.employee_max, categories = EXCLUDED.categories, fetched_at = now()""",
        (company_id, org.get("total_usd"), org.get("last_round_type"), org.get("founded_on"),
         org.get("employee_min"), org.get("employee_max"), org.get("categories") or []))


def save_tech(conn, company_id: int, techs: list[dict]) -> None:
    conn.execute("DELETE FROM tech_stack WHERE company_id = %s", (company_id,))
    for t in techs:
        conn.execute(
            "INSERT INTO tech_stack (company_id, technology, category, live) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (company_id, t["technology"], t.get("category"), t.get("live", True)))


def save_postings(conn, company_id: int, postings: list[dict]) -> dict:
    """Upsert the current board and mark postings that disappeared as inactive."""
    seen = []
    for p in postings:
        family, seniority = classify_title(p["title"])
        conn.execute(
            """INSERT INTO job_postings (id, company_id, source, title, role_family, seniority, location, remote,
                                         url, posted_at, pay_min, pay_max, pay_currency, description)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                 title = EXCLUDED.title, role_family = EXCLUDED.role_family, seniority = EXCLUDED.seniority,
                 location = EXCLUDED.location, remote = EXCLUDED.remote, url = EXCLUDED.url,
                 pay_min = EXCLUDED.pay_min, pay_max = EXCLUDED.pay_max, pay_currency = EXCLUDED.pay_currency,
                 description = EXCLUDED.description, last_seen = now(), active = true""",
            (p["id"], company_id, p["source"], p["title"], family, seniority, p.get("location"), p.get("remote"),
             p.get("url"), p.get("posted_at"), p.get("pay_min"), p.get("pay_max"), p.get("pay_currency"),
             p.get("description")))
        seen.append(p["id"])
    closed = conn.execute(
        "UPDATE job_postings SET active = false WHERE company_id = %s AND active AND NOT (id = ANY(%s))",
        (company_id, seen)).rowcount
    return {"active": len(seen), "closed": closed}


def save_levels(conn, records: list[dict]) -> dict:
    inserted = skipped = 0
    for r in records:
        cid = upsert_company(conn, r["company"])
        cur = conn.execute(
            """INSERT INTO levels_comp (company_id, title, level, role_family, seniority, base_usd, total_usd,
                                        years_exp, location, reported_on, source_file, row_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (row_hash) DO NOTHING""",
            (cid, r["title"], r["level"], r["role_family"], r["seniority"], r["base_usd"], r["total_usd"],
             r["years_exp"], r["location"], r["reported_on"], r["source_file"], r["row_hash"]))
        inserted += cur.rowcount
        skipped += 1 - cur.rowcount
    return {"inserted": inserted, "skipped_duplicates": skipped}


def save_insights(conn, company_id: int, insights: dict) -> None:
    conn.execute(
        """INSERT INTO company_insights (company_id, open_roles, new_roles_30d, pay, competitiveness, interview, computed_at)
           VALUES (%s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (company_id) DO UPDATE SET
             open_roles = EXCLUDED.open_roles, new_roles_30d = EXCLUDED.new_roles_30d, pay = EXCLUDED.pay,
             competitiveness = EXCLUDED.competitiveness, interview = EXCLUDED.interview, computed_at = now()""",
        (company_id, insights["open_roles"], insights["new_roles_30d"], Jsonb(insights["pay"]),
         Jsonb(insights["competitiveness"]) if insights.get("competitiveness") else None,
         Jsonb(insights["interview"])))
