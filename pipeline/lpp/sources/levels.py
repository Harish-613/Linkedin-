"""Levels.fyi compensation data, imported from a CSV or JSON file.

Levels.fyi has no public API and its terms prohibit scraping, so the pipeline
never fetches levels.fyi pages. Instead it imports a file you obtained
legitimately (a Levels.fyi data export or licensed dataset, or the widely
mirrored public dataset with columns like company, title, level,
totalyearlycompensation, basesalary, yearsofexperience, location, timestamp).
Column names are matched case-insensitively against the aliases below.
"""

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from lpp.normalize import classify_title

ALIASES = {
    "company": ["company", "company_name", "employer"],
    "title": ["title", "job_title", "role"],
    "level": ["level", "level_name"],
    "base": ["basesalary", "base_salary", "base", "salary"],
    "total": ["totalyearlycompensation", "total_compensation", "total_comp", "tc", "total"],
    "years": ["yearsofexperience", "years_of_experience", "yoe"],
    "location": ["location", "city"],
    "date": ["timestamp", "date", "reported_at", "reported_on"],
}


def _pick(row: dict, field: str):
    lower = {k.lower().strip(): v for k, v in row.items()}
    for alias in ALIASES[field]:
        v = lower.get(alias)
        if v not in (None, ""):
            return v
    return None


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _date(v) -> str | None:
    if not v:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(v)[:19], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def read_rows(path: str) -> list[dict]:
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else data.get("rows", [])
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_rows(rows: list[dict], source_file: str, unit: float = 1.0) -> list[dict]:
    """unit=1000 for files that report pay in thousands (e.g. 185 meaning $185k)."""
    out = []
    for row in rows:
        company, title = _pick(row, "company"), _pick(row, "title")
        if not company or not title:
            continue
        base, total = _num(_pick(row, "base")), _num(_pick(row, "total"))
        base = base * unit if base is not None else None
        total = total * unit if total is not None else None
        if not base and not total:
            continue
        family, seniority = classify_title(f"{_pick(row, 'level') or ''} {title}")
        record = {
            "company": str(company).strip(),
            "title": str(title).strip(),
            "level": _pick(row, "level"),
            "role_family": family,
            "seniority": seniority,
            "base_usd": base,
            "total_usd": total,
            "years_exp": _num(_pick(row, "years")),
            "location": _pick(row, "location"),
            "reported_on": _date(_pick(row, "date")),
            "source_file": Path(source_file).name,
        }
        key = json.dumps({k: record[k] for k in record if k != "source_file"}, sort_keys=True, default=str)
        record["row_hash"] = hashlib.blake2b(key.encode(), digest_size=16).hexdigest()
        out.append(record)
    return out
