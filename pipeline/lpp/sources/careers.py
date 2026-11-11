"""Company career pages through the public job-board APIs of the three most
common applicant tracking systems. All are unauthenticated and meant for
embedding job listings on careers sites.

  Greenhouse  https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  Lever       https://api.lever.co/v0/postings/{site}?mode=json
  Ashby       https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true

Every parser returns the same normalized posting dict. Pay comes from the
structured salary fields when the ATS exposes them, otherwise from the pay
range that US pay-transparency laws put in the description text.
"""

import html
import re
from datetime import datetime, timezone

from lpp.normalize import annualize

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{token}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

_TAG = re.compile(r"<[^>]+>")
_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
_UNIT = r"(?:\s*(?:USD))?(?:\s*(?:/|per|an|a)\s*(hour|hr|year|yr|annum|annually))?"
_RANGE = re.compile(_MONEY + _UNIT + r"\s*(?:-|–|—|to)\s*" + _MONEY + _UNIT, re.IGNORECASE)


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(html.unescape(s))  # Greenhouse double-escapes content
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = _TAG.sub(" ", s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def _amount(num: str, k: str | None) -> float:
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def extract_pay_from_text(text: str) -> tuple[float, float] | None:
    """Find a salary range like "$140,000 - $180,000" or "$55/hr to $65/hr"; returns annualized (min, max)."""
    for m in _RANGE.finditer(text or ""):
        lo, hi = _amount(m.group(1), m.group(2)), _amount(m.group(4), m.group(5))
        unit = (m.group(6) or m.group(3) or "").lower()
        if lo > hi:
            lo, hi = hi, lo
        if unit in ("hour", "hr") or hi < 500:
            if not 10 <= lo <= 1000:
                continue
            lo, hi = lo * 2080, hi * 2080
        if 15_000 <= lo <= 2_000_000 and hi <= lo * 4:  # reject stock/bonus amounts and junk
            return lo, hi
    return None


def _posting(source, ext_id, title, location, remote, url, posted_at, pay, currency, description):
    if pay is None:
        pay = extract_pay_from_text(description)
        currency = "USD" if pay else None
    return {
        "id": f"{source}:{ext_id}",
        "source": source,
        "title": title.strip(),
        "location": location or None,
        "remote": remote,
        "url": url,
        "posted_at": posted_at,
        "pay_min": pay[0] if pay else None,
        "pay_max": pay[1] if pay else None,
        "pay_currency": currency,
        "description": description[:20000],
    }


def parse_greenhouse(data: dict) -> list[dict]:
    out = []
    for j in data.get("jobs", []):
        description = html_to_text(j.get("content"))
        loc = (j.get("location") or {}).get("name", "")
        pay = None
        ranges = j.get("pay_input_ranges") or []  # present when fetched with pay_transparency=true
        if ranges:
            r = ranges[0]
            pay = (r["min_cents"] / 100, r["max_cents"] / 100)
        out.append(_posting(
            "greenhouse", j["id"], j["title"], loc, "remote" in loc.lower(), j.get("absolute_url"),
            j.get("updated_at") or j.get("first_published"), pay,
            ranges[0].get("currency_type") if ranges else None, description))
    return out


def parse_lever(data: list) -> list[dict]:
    out = []
    for p in data:
        cats = p.get("categories") or {}
        sr = p.get("salaryRange") or {}
        pay = None
        if sr.get("min") is not None and sr.get("max") is not None:
            lo, hi = annualize(sr["min"], sr.get("interval")), annualize(sr["max"], sr.get("interval"))
            pay = (lo, hi) if lo and hi else None
        parts = [p.get("descriptionPlain") or ""]
        parts += [f"{l.get('text', '')}\n{html_to_text(l.get('content'))}" for l in p.get("lists") or []]
        parts.append(p.get("additionalPlain") or "")
        created = p.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else None
        out.append(_posting(
            "lever", p["id"], p["text"], cats.get("location"), (p.get("workplaceType") or "").lower() == "remote",
            p.get("hostedUrl"), posted, pay, sr.get("currency") if pay else None, "\n".join(parts).strip()))
    return out


def _ashby_salary(comp: dict | None) -> tuple[tuple[float, float] | None, str | None]:
    for c in (comp or {}).get("summaryComponents") or []:
        if c.get("compensationType") == "Salary" and c.get("minValue") and c.get("maxValue"):
            interval = (c.get("interval") or "1 YEAR").lower()
            lo, hi = annualize(c["minValue"], interval), annualize(c["maxValue"], interval)
            if lo and hi:
                return (lo, hi), c.get("currencyCode")
    return None, None


def parse_ashby(data: dict) -> list[dict]:
    out = []
    board_comp = data.get("compensation")  # some responses put it at the top level
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        pay, currency = _ashby_salary(j.get("compensation") or board_comp)
        ext_id = j.get("id") or (j.get("jobUrl") or j["title"]).rstrip("/").rsplit("/", 1)[-1]
        out.append(_posting(
            "ashby", ext_id, j["title"], j.get("location"), bool(j.get("isRemote")), j.get("jobUrl"),
            j.get("publishedAt"), pay, currency, j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))))
    return out


def fetch_postings(client, provider: str, token: str) -> list[dict]:
    if provider == "greenhouse":
        return parse_greenhouse(client.get_json(GREENHOUSE_URL.format(token=token), params={"content": "true"}))
    if provider == "lever":
        return parse_lever(client.get_json(LEVER_URL.format(token=token), params={"mode": "json"}))
    if provider == "ashby":
        return parse_ashby(client.get_json(ASHBY_URL.format(token=token), params={"includeCompensation": "true"}))
    raise ValueError(f"unknown ATS provider: {provider}")
