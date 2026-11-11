"""SEC EDGAR (free, no key; a User-Agent with contact info is required).

* company_tickers.json: every listed company (~10k) with ticker and CIK.
* submissions/CIK##########.json: industry (SIC) and state of incorporation.
* api/xbrl/companyfacts/CIK##########.json: reported financials. We take
  annual revenue and net income from 10-K filings.
"""

from datetime import date

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Companies report revenue under different XBRL concepts depending on era and industry.
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
NET_INCOME_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]


def parse_tickers(data: dict) -> list[dict]:
    """{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...} -> one row per CIK.

    The file lists a company once per share class; the first entry is kept.
    """
    seen, out = set(), []
    for row in data.values():
        cik = int(row["cik_str"])
        if cik in seen:
            continue
        seen.add(cik)
        out.append({"cik": cik, "ticker": row["ticker"], "name": row["title"]})
    return out


def parse_submissions(data: dict) -> dict:
    return {
        "name": data.get("name"),
        "sic_description": data.get("sicDescription") or None,
        "state": data.get("stateOfIncorporation") or None,
        "website": data.get("website") or None,
    }


def _annual_values(units: list[dict]) -> dict[str, float]:
    """period-end date -> value, for ~12-month periods reported on 10-K forms (latest filing wins)."""
    by_end: dict[str, tuple[str, float]] = {}
    for f in units:
        if not str(f.get("form", "")).startswith("10-K") or "start" not in f:
            continue
        days = (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
        if not 350 <= days <= 380:
            continue  # quarterly or partial period
        prev = by_end.get(f["end"])
        if prev is None or f.get("filed", "") > prev[0]:
            by_end[f["end"]] = (f.get("filed", ""), float(f["val"]))
    return {end: v for end, (_, v) in by_end.items()}


def _latest_concept(facts: dict, concepts: list[str]) -> dict[str, float]:
    """Annual series from whichever concept has the most recent fiscal year."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    best: dict[str, float] = {}
    for concept in concepts:
        series = _annual_values(gaap.get(concept, {}).get("units", {}).get("USD", []))
        if series and (not best or max(series) > max(best)):
            best = series
    return best


def parse_company_facts(data: dict) -> dict | None:
    revenue = _latest_concept(data, REVENUE_CONCEPTS)
    income = _latest_concept(data, NET_INCOME_CONCEPTS)
    if not revenue and not income:
        return None
    latest_end = max(revenue or income)
    growth = None
    if revenue:
        ends = sorted(revenue)
        last = ends[-1]
        prior = [e for e in ends if 330 <= (date.fromisoformat(last) - date.fromisoformat(e)).days <= 400]
        if prior and revenue[prior[-1]]:
            growth = revenue[last] / revenue[prior[-1]] - 1
    return {
        "fiscal_year": int(latest_end[:4]),
        "revenue_usd": revenue.get(latest_end) if revenue else None,
        "net_income_usd": income.get(latest_end) if income else None,
        "revenue_growth": growth,
    }


def fetch_tickers(client) -> list[dict]:
    return parse_tickers(client.get_json(TICKERS_URL))


def fetch_company(client, cik: int) -> dict:
    sub = parse_submissions(client.get_json(SUBMISSIONS_URL.format(cik=cik)))
    try:
        facts = parse_company_facts(client.get_json(FACTS_URL.format(cik=cik))) or {}
    except Exception:  # many filers (funds, shells) have no XBRL facts
        facts = {}
    return {**sub, **facts}
