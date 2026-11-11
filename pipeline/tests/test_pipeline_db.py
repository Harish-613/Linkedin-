"""End-to-end: run the real CLI against a throwaway Postgres database, with
every HTTP call answered from the recorded fixtures."""

import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest

from lpp import cli, db
from lpp.http import HttpClient, NotFound

FIX = Path(__file__).parent / "fixtures"
ADMIN_DSN = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5432/postgres")


@pytest.fixture
def database(monkeypatch):
    name = f"lpp_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("no Postgres available")
    admin.execute(f"CREATE DATABASE {name}")
    dsn = ADMIN_DSN.rsplit("/", 1)[0] + f"/{name}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    yield dsn
    admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
    admin.close()


ROUTES = {
    "https://www.sec.gov/files/company_tickers.json": "sec_tickers.json",
    "https://data.sec.gov/submissions/CIK0001679788.json": "sec_submissions_coin.json",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0001679788.json": "sec_companyfacts_coin.json",
    "https://boards-api.greenhouse.io/v1/boards/coinbase/jobs": "greenhouse_jobs.json",
    "https://api.lever.co/v0/postings/palantir": "lever_postings.json",
    "https://api.ashbyhq.com/posting-api/job-board/ramp": "ashby_board.json",
    "https://api.crunchbase.com/api/v4/entities/organizations/ramp-2": "crunchbase_org.json",
    "https://api.builtwith.com/free1/api.json": "builtwith_free.json",
}


@pytest.fixture
def fake_http(monkeypatch):
    requested = []

    def get_json(self, url, params=None, headers=None):
        requested.append(url)
        if url in ROUTES:
            return json.loads((FIX / ROUTES[url]).read_text())
        raise NotFound(url)

    monkeypatch.setattr(HttpClient, "get_json", get_json)
    return requested


@pytest.fixture
def seeds(tmp_path):
    p = tmp_path / "seeds.csv"
    p.write_text("name,domain,ats_provider,ats_token,crunchbase_permalink,aliases\n"
                 "Coinbase,coinbase.com,greenhouse,coinbase,,\n"
                 "Palantir,palantir.com,lever,palantir,,\n"
                 "Ramp,ramp.com,ashby,ramp,ramp-2,Ramp Business\n"
                 "Typo Co,typo.com,greenhouse,not-a-board,,\n")
    return str(p)


def test_full_pipeline(database, fake_http, seeds, monkeypatch, capsys):
    monkeypatch.setenv("CRUNCHBASE_API_KEY", "test")
    monkeypatch.setenv("BUILTWITH_API_KEY", "test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cli.main(["all", "--seeds", seeds, "--details", "5"])
    cli.main(["import-levels", str(FIX / "levels.csv")])
    cli.main(["import-levels", str(FIX / "levels.csv")])  # second import is a no-op
    cli.main(["compute"])
    out = capsys.readouterr().out
    assert "SEC: 4 listed companies" in out
    assert "board 'not-a-board' not found" in out
    # The file repeats one row, so the first import already skips it once.
    assert "3 rows imported, 1 already present" in out and "0 rows imported, 4 already present" in out

    conn = db.connect(database)
    # Entity resolution: the seed file's "Coinbase" and SEC's "Coinbase Global, Inc." are one company,
    # so its job postings and its financials end up together.
    coin = db.find_company(conn, name="Coinbase")
    assert coin == db.find_company(conn, cik=1679788) == db.find_company(conn, domain="coinbase.com")
    assert conn.execute("SELECT count(*) FROM job_postings WHERE company_id = %s", (coin,)).fetchone()[0] == 2
    fin = conn.execute("SELECT revenue_usd, fiscal_year FROM sec_financials WHERE company_id = %s", (coin,)).fetchone()
    assert fin == (6564028000, 2024)

    ramp = db.find_company(conn, name="Ramp Business")          # alias from the seed file
    assert ramp == db.find_company(conn, domain="https://ramp.com/")
    assert conn.execute("SELECT employee_min, last_round_type FROM funding WHERE company_id = %s",
                        (ramp,)).fetchone() == (1001, "series_e")
    assert conn.execute("SELECT count(*) FROM tech_stack WHERE company_id = %s", (ramp,)).fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM job_postings WHERE company_id = %s AND active", (ramp,)).fetchone()[0] == 2

    pay, interview, comp = conn.execute(
        "SELECT pay, interview, competitiveness FROM company_insights WHERE company_id = %s", (ramp,)).fetchone()
    # "Software Engineer, Backend" (posting) is classified backend; Levels rows say "Software Engineer".
    assert pay["backend"]["all"]["sources"] == {"postings": 1}
    assert pay["software_engineering"]["all"]["sources"] == {"levels": 2}
    assert pay["software_engineering"]["senior"]["p50"] == 205000
    assert interview["backend"]["method"] == "heuristic"
    assert comp is None  # only 4 companies in the db: below the ranking population

    # Re-sync after a posting disappears: it is marked inactive, not deleted.
    board = json.loads((FIX / "ashby_board.json").read_text())
    board["jobs"] = board["jobs"][:1]
    monkeypatch.setitem(ROUTES, "https://api.ashbyhq.com/posting-api/job-board/ramp", "ashby_one.json")
    (FIX / "ashby_one.json").write_text(json.dumps(board))
    try:
        cli.main(["sync-careers", "--seeds", seeds])
    finally:
        (FIX / "ashby_one.json").unlink()
    assert conn.execute("SELECT count(*) FILTER (WHERE active), count(*) FROM job_postings WHERE company_id = %s",
                        (ramp,)).fetchone() == (1, 2)
    conn.close()


def test_entity_resolution_prefers_strong_identifiers(database):
    conn = db.connect(database)
    db.init_schema(conn)
    a = db.upsert_company(conn, "Alphabet Inc.", cik=1652044, ticker="GOOGL")
    b = db.upsert_company(conn, "Google", domain="google.com", aliases=["Alphabet"])  # alias links to the SEC row
    assert a == b
    assert db.find_company(conn, name="GOOGL") == a
    assert db.find_company(conn, domain="www.google.com") == a
    assert conn.execute("SELECT domain, cik FROM companies WHERE id = %s", (a,)).fetchone() == ("google.com", 1652044)
    conn.close()
