import json
from pathlib import Path

import pytest

from lpp.normalize import annualize, classify_title, normalize_company, normalize_domain
from lpp.sources import builtwith, careers, crunchbase, levels, sec

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


# ---------------------------------------------------------------- normalize

@pytest.mark.parametrize("raw,expected", [
    ("Stripe, Inc.", "stripe"),
    ("Coinbase Global, Inc.", "coinbase"),
    ("Robinhood Markets, Inc.", "robinhood"),
    ("Meta Platforms, Inc.", "meta"),
    ("Palantir Technologies Inc.", "palantir"),
    ("The Walt Disney Company", "walt disney"),
    ("AT&amp;T Inc.", "at&t"),
    ("Société Générale S.A.", "societe generale"),
    ("Labs", "labs"),  # never strip down to nothing
])
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


def test_normalize_domain():
    assert normalize_domain("https://www.Stripe.com/jobs?x=1") == "stripe.com"
    assert normalize_domain("ramp.com") == "ramp.com"
    assert normalize_domain("") is None


@pytest.mark.parametrize("title,family,level", [
    ("Software Engineer, New Grad (2027)", "software_engineering", "new_grad"),
    ("Senior Machine Learning Engineer - Remote (USA)", "machine_learning", "senior"),
    ("Staff Backend Engineer, Payments", "backend", "staff_plus"),
    ("Software Engineer Intern", "software_engineering", "intern"),
    ("iOS Engineer II", "mobile", "mid"),
    ("Quantitative Researcher", "quant", "mid"),
    ("Engineering Manager, Infrastructure", "infrastructure", "manager"),
    ("Product Designer", "design", "mid"),
    ("Account Executive, Enterprise", "sales", "mid"),
    ("VP of Finance", "finance", "executive"),
    ("Chef", "other", "mid"),
])
def test_classify_title(title, family, level):
    assert classify_title(title) == (family, level)


def test_annualize():
    assert annualize(55, "per-hour-wage") == 55 * 2080
    assert annualize(10000, "1 MONTH") == 120000
    assert annualize(150000, None) == 150000
    assert annualize(1, "fortnight") is None


# ---------------------------------------------------------------- SEC

def test_sec_tickers_dedupes_share_classes():
    rows = sec.parse_tickers(load("sec_tickers.json"))
    assert [r["ticker"] for r in rows] == ["AAPL", "GOOGL", "COIN", "PLTR"]
    assert rows[2] == {"cik": 1679788, "ticker": "COIN", "name": "Coinbase Global, Inc."}


def test_sec_company_facts_annual_revenue_and_growth():
    f = sec.parse_company_facts(load("sec_companyfacts_coin.json"))
    assert f["fiscal_year"] == 2024
    assert f["revenue_usd"] == 6564028000          # the 12-month figure, not the Q4 one
    assert f["net_income_usd"] == 2579066000
    assert f["revenue_growth"] == pytest.approx(6564028000 / 3108383000 - 1)


def test_sec_submissions():
    s = sec.parse_submissions(load("sec_submissions_coin.json"))
    assert s == {"name": "Coinbase Global, Inc.", "sic_description": "Finance Services", "state": "DE", "website": None}


def test_sec_no_facts():
    assert sec.parse_company_facts({"facts": {}}) is None


# ---------------------------------------------------------------- career pages

def test_greenhouse_parses_content_and_both_pay_sources():
    jobs = careers.parse_greenhouse(load("greenhouse_jobs.json"))
    assert [j["id"] for j in jobs] == ["greenhouse:6012345", "greenhouse:6012399"]
    first, second = jobs
    assert "algorithms and data structures" in first["description"]   # HTML double-unescaped
    assert "<" not in first["description"]
    assert (first["pay_min"], first["pay_max"], first["pay_currency"]) == (140000, 160000, "USD")  # from text
    assert (second["pay_min"], second["pay_max"]) == (221000, 260000)  # from pay_input_ranges (cents)
    assert second["remote"] is True


def test_lever_salary_ranges_including_hourly():
    posts = careers.parse_lever(load("lever_postings.json"))
    assert posts[0]["pay_min"] == 135000 and posts[0]["pay_max"] == 200000
    assert posts[1]["pay_min"] == 55 * 2080                      # hourly intern pay annualized
    assert "3+ years experience" in posts[0]["description"]      # lists are included
    assert posts[0]["posted_at"].startswith("2025-10-27")


def test_ashby_compensation_skips_unlisted_and_reads_text_pay():
    jobs = careers.parse_ashby(load("ashby_board.json"))
    assert [j["title"] for j in jobs] == ["Software Engineer, Backend", "Product Designer"]
    assert (jobs[0]["pay_min"], jobs[0]["pay_max"]) == (170000, 260000)
    assert (jobs[1]["pay_min"], jobs[1]["pay_max"]) == (150000, 190000)  # "$150k to $190k" in text
    assert jobs[0]["id"] == "ashby:7f0e8a1c-1111-4222-8333-444455556666"


@pytest.mark.parametrize("text,expected", [
    ("Base salary range: $120,000 - $145,000 per year", (120000, 145000)),
    ("$95K–$120K + equity", (95000, 120000)),
    ("Pay: $45/hr to $50/hr", (45 * 2080, 50 * 2080)),
    ("We offer $10,000 - $20,000 in relocation and a $5,000 - $8,000 stipend", None),  # too low to be salary
    ("Equity grant $100,000 - $900,000 over 4 years", None),  # implausible spread
    ("No numbers here", None),
])
def test_extract_pay_from_text(text, expected):
    assert careers.extract_pay_from_text(text) == expected


# ---------------------------------------------------------------- Crunchbase / BuiltWith / Levels

def test_crunchbase_org_and_autocomplete():
    org = crunchbase.parse_organization(load("crunchbase_org.json"))
    assert org == {"permalink": "ramp-2", "name": "Ramp", "website": "https://ramp.com", "total_usd": 1900000000,
                   "last_round_type": "series_e", "founded_on": "2019-03-01", "employee_min": 1001,
                   "employee_max": 5000, "categories": ["FinTech", "Finance"]}
    assert crunchbase.parse_autocomplete(load("crunchbase_autocomplete.json")) == "ramp-2"
    assert crunchbase.parse_employee_enum("c_10001_max") == (10001, None)


def test_builtwith_domain_and_free_api():
    techs = builtwith.parse_builtwith(load("builtwith_domain.json"))
    assert techs == [{"technology": "Cloudflare", "category": "CDN", "live": True},
                     {"technology": "React", "category": "JavaScript Library", "live": True}]
    free = builtwith.parse_builtwith(load("builtwith_free.json"))
    assert {"technology": "category:Application Performance", "category": "analytics", "live": True} in free
    assert {"technology": "category:Conversion Optimization", "category": "analytics", "live": False} in free


def test_levels_csv_import():
    rows = levels.parse_rows(levels.read_rows(str(FIX / "levels.csv")), "levels.csv")
    assert len(rows) == 4                       # blank-company row dropped
    assert rows[0]["company"] == "Ramp" and rows[0]["base_usd"] == 165000 and rows[0]["total_usd"] == 215000
    assert rows[1]["seniority"] == "senior"
    assert rows[1]["row_hash"] == rows[2]["row_hash"]   # exact duplicate rows hash the same
    assert rows[0]["reported_on"] == "2026-06-07"
    thousands = levels.parse_rows([{"company": "X", "title": "SWE", "basesalary": "185"}], "f.csv", unit=1000)
    assert thousands[0]["base_usd"] == 185000
