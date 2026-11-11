"""lpp: the LinkedIn++ data pipeline.

  lpp init-db                       create tables (safe to re-run)
  lpp sync-sec [--details N]        all SEC-listed companies (~10k); --details fetches financials for N of them
  lpp sync-careers [--seeds CSV]    job postings from Greenhouse / Lever / Ashby boards in the seed file
  lpp sync-crunchbase [--limit N]   funding + headcount (needs CRUNCHBASE_API_KEY)
  lpp sync-builtwith [--limit N]    tech stack (needs BUILTWITH_API_KEY; --paid for the Domain API)
  lpp import-levels FILE [--unit 1000]   Levels.fyi data from a CSV/JSON file you provide
  lpp compute                       recompute pay ranges, competitiveness, interview difficulty
  lpp all                           init-db + every sync whose key is configured + compute
  lpp stats                         row counts per table

DATABASE_URL selects the database (Supabase connection strings work).
"""

import argparse
import csv
import os
import sys
from pathlib import Path

from lpp import db, insights, llm
from lpp.http import HttpClient, NotFound
from lpp.sources import builtwith, careers, crunchbase, levels, sec

DEFAULT_SEEDS = Path(__file__).resolve().parents[1] / "seeds" / "companies.csv"


def cmd_sync_sec(conn, client, args):
    rows = sec.fetch_tickers(client)
    for r in rows:
        db.upsert_company(conn, r["name"], cik=r["cik"], ticker=r["ticker"])
    conn.commit()
    print(f"SEC: {len(rows):,} listed companies")
    if args.details:
        ciks = [r["cik"] for r in rows[: args.details]]  # file is ordered by market cap
        for i, cik in enumerate(ciks, 1):
            try:
                info = sec.fetch_company(client, cik)
            except NotFound:
                continue
            cid = db.find_company(conn, cik=cik)
            if info.get("website"):
                conn.execute("UPDATE companies SET domain = COALESCE(domain, %s) WHERE id = %s",
                             (db.normalize_domain(info["website"]), cid))
            db.save_sec(conn, cid, info)
            if i % 50 == 0:
                conn.commit()
                print(f"  financials {i}/{len(ciks)}")
        conn.commit()


def read_seeds(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("name") and not r["name"].startswith("#")]


def cmd_sync_careers(conn, client, args):
    ok = failed = 0
    for seed in read_seeds(args.seeds):
        if not seed.get("ats_provider") or not seed.get("ats_token"):
            continue
        cid = db.upsert_company(conn, seed["name"], domain=seed.get("domain") or None,
                                aliases=[a for a in (seed.get("aliases") or "").split(";") if a],
                                ats_provider=seed["ats_provider"], ats_token=seed["ats_token"],
                                crunchbase_permalink=seed.get("crunchbase_permalink") or None)
        try:
            postings = careers.fetch_postings(client, seed["ats_provider"], seed["ats_token"])
        except NotFound:
            print(f"  {seed['name']}: board '{seed['ats_token']}' not found on {seed['ats_provider']} (check the token)")
            failed += 1
            conn.commit()
            continue
        result = db.save_postings(conn, cid, postings)
        with_pay = sum(1 for p in postings if p["pay_min"])
        print(f"  {seed['name']}: {result['active']} open roles ({with_pay} with pay), {result['closed']} closed")
        conn.commit()
        ok += 1
    print(f"Career pages: {ok} boards synced, {failed} failed")


def _companies_needing(conn, column_sql: str, limit: int):
    return conn.execute(f"SELECT id, name, domain, crunchbase_permalink FROM companies WHERE {column_sql} "
                        "ORDER BY (ats_token IS NULL), id LIMIT %s", (limit,)).fetchall()


def cmd_sync_crunchbase(conn, client, args):
    key = os.environ.get("CRUNCHBASE_API_KEY")
    if not key:
        sys.exit("set CRUNCHBASE_API_KEY")
    rows = _companies_needing(conn, "id NOT IN (SELECT company_id FROM funding)", args.limit)
    for cid, name, _domain, permalink in rows:
        try:
            permalink = permalink or crunchbase.find_permalink(client, name, key)
            if not permalink:
                continue
            org = crunchbase.fetch_organization(client, permalink, key)
        except NotFound:
            continue
        conn.execute("UPDATE companies SET crunchbase_permalink = %s WHERE id = %s", (permalink, cid))
        if org.get("website"):
            conn.execute("UPDATE companies SET domain = COALESCE(domain, %s) WHERE id = %s AND NOT EXISTS "
                         "(SELECT 1 FROM companies WHERE domain = %s)",
                         (db.normalize_domain(org["website"]), cid, db.normalize_domain(org["website"])))
        db.save_funding(conn, cid, org)
        conn.commit()
    print(f"Crunchbase: {len(rows)} companies looked up")


def cmd_sync_builtwith(conn, client, args):
    key = os.environ.get("BUILTWITH_API_KEY")
    if not key:
        sys.exit("set BUILTWITH_API_KEY")
    rows = _companies_needing(conn, "domain IS NOT NULL AND id NOT IN (SELECT company_id FROM tech_stack)", args.limit)
    for cid, _name, domain, _ in rows:
        try:
            db.save_tech(conn, cid, builtwith.fetch_tech(client, domain, key, paid=args.paid))
        except NotFound:
            continue
        conn.commit()
    print(f"BuiltWith: {len(rows)} domains looked up")


def cmd_import_levels(conn, args):
    records = levels.parse_rows(levels.read_rows(args.file), args.file, unit=args.unit)
    result = db.save_levels(conn, records)
    conn.commit()
    print(f"Levels.fyi: {result['inserted']} rows imported, {result['skipped_duplicates']} already present")


def cmd_compute(conn):
    model = llm.from_env(conn)
    n = insights.compute_all(conn, llm=model)
    used = f" (LLM: {model.calls} calls, {model.hits} cached)" if model else " (heuristic interview scores; set OPENAI_API_KEY for LLM)"
    print(f"Insights computed for {n:,} companies{used}")


def cmd_stats(conn):
    for table in ("companies", "company_aliases", "sec_financials", "funding", "tech_stack", "job_postings",
                  "levels_comp", "company_insights", "llm_cache"):
        print(f"  {table:<18} {conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:>8,}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="lpp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    s = sub.add_parser("sync-sec")
    s.add_argument("--details", type=int, default=0, help="also fetch financials for the N largest companies")
    s = sub.add_parser("sync-careers")
    s.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    for name in ("sync-crunchbase", "sync-builtwith"):
        s = sub.add_parser(name)
        s.add_argument("--limit", type=int, default=200)
        if name == "sync-builtwith":
            s.add_argument("--paid", action="store_true", help="use the paid Domain API (technology names)")
    s = sub.add_parser("import-levels")
    s.add_argument("file")
    s.add_argument("--unit", type=float, default=1.0, help="multiply pay columns, e.g. 1000 if the file is in $k")
    sub.add_parser("compute")
    s = sub.add_parser("all")
    s.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    s.add_argument("--details", type=int, default=200)
    s.add_argument("--limit", type=int, default=200)
    s.add_argument("--paid", action="store_true")
    sub.add_parser("stats")
    args = p.parse_args(argv)

    conn = db.connect()
    client = HttpClient()
    if args.cmd in ("init-db", "all"):
        db.init_schema(conn)
        print("Schema ready")
    if args.cmd in ("sync-sec", "all"):
        cmd_sync_sec(conn, client, args)
    if args.cmd in ("sync-careers", "all"):
        cmd_sync_careers(conn, client, args)
    if args.cmd == "sync-crunchbase" or (args.cmd == "all" and os.environ.get("CRUNCHBASE_API_KEY")):
        cmd_sync_crunchbase(conn, client, args)
    if args.cmd == "sync-builtwith" or (args.cmd == "all" and os.environ.get("BUILTWITH_API_KEY")):
        cmd_sync_builtwith(conn, client, args)
    if args.cmd == "import-levels":
        cmd_import_levels(conn, args)
    if args.cmd in ("compute", "all"):
        cmd_compute(conn)
    if args.cmd == "stats":
        cmd_stats(conn)
    conn.close()


if __name__ == "__main__":
    main()
