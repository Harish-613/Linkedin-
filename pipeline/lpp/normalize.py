"""Company-name matching, job-title classification and pay annualization.

Rules live in shared/rules.json so the TypeScript API classifies the exact
same way when the extension sends a LinkedIn job title.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[2] / "shared" / "rules.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    data = json.loads(RULES_PATH.read_text())
    data["_families"] = [(r["family"], [re.compile(p) for p in r["patterns"]]) for r in data["role_families"]]
    data["_seniority"] = [(r["level"], [re.compile(p) for p in r["patterns"]]) for r in data["seniority"]]
    return data


def normalize_company(name: str) -> str:
    """'Stripe, Inc.' -> 'stripe'; 'Alphabet Inc. (Google)' -> 'alphabet google'; 'AT&T Inc.' -> 'at&t'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&amp;", "&").replace(".", "")  # "S.A." -> "sa", "U.S." -> "us"
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    words = s.split()
    suffixes = set(rules()["company_suffixes"])
    while len(words) > 1 and words[-1] in suffixes:  # strip trailing legal suffixes, keep at least one word
        words.pop()
    if len(words) > 1 and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def normalize_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    d = url_or_domain.strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split("?")[0]
    d = d.removeprefix("www.")
    return d or None


def _clean_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)          # (Remote), [US]
    t = re.sub(r"[,/|–—-]+\s*(remote|hybrid|on-?site|us|usa|united states).*$", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify_title(title: str) -> tuple[str, str]:
    """Job title -> (role_family, seniority). Unknown families fall back to 'other'."""
    t = _clean_title(title)
    family = next((f for f, pats in rules()["_families"] if any(p.search(t) for p in pats)), "other")
    seniority = next(lvl for lvl, pats in rules()["_seniority"] if any(p.search(t) for p in pats))
    return family, seniority


def annualize(amount: float | None, interval: str | None) -> float | None:
    """Convert a pay amount to yearly using shared/rules.json intervals (hourly assumes 2,080 h)."""
    if amount is None:
        return None
    key = (interval or "year").strip().lower()
    factor = rules()["pay_intervals_per_year"].get(key)
    if factor is None:
        return None
    return float(amount) * factor
