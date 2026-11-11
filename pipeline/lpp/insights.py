"""Turn raw source data into the three things the extension shows.

Pay ranges
    Per company, role family and seniority: 25th/50th/75th percentile of base
    pay, pooling (a) the midpoint of each posted salary range and (b) Levels.fyi
    base salaries. `n` and per-source counts are always reported so a range
    built from 3 data points doesn't look as solid as one built from 300.

Hiring competitiveness (0-100)
    How hard it likely is to get an offer, from public signals ranked against
    every other company in the database:
      pay        median offered pay (higher pay draws more applicants)     35%
      scarcity   open roles per 100 employees (fewer seats = harder)       25%
      scale      revenue (SEC) or total funding (Crunchbase)               25%
      momentum   share of open roles posted in the last 30 days            15%
    (momentum counts *against* competitiveness: a company hiring fast
    accepts more people.) Missing factors are dropped and the remaining
    weights rescaled; fewer than two factors means no score.

Interview difficulty (1-5), per role family
    Heuristic from the company's own job descriptions: required years of
    experience, how often algorithms / system design / coding assessments are
    mentioned, advanced-degree requirements, plus hiring competitiveness.
    When an OpenAI key is configured, an LLM reads sample requirement
    sections with those signals and returns a score with a short rationale.
    Either way it is an estimate from public requirements, and labelled as such.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

WEIGHTS = {"pay": 0.35, "scarcity": 0.25, "scale": 0.25, "momentum": 0.15}
MIN_POPULATION = 5  # need this many companies with a factor before ranking on it


# ---------------------------------------------------------------- pay

def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already sorted list (q in 0..1)."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def summarize(samples: list[tuple[float, str]]) -> dict:
    values = sorted(v for v, _ in samples)
    sources = defaultdict(int)
    for _, s in samples:
        sources[s] += 1
    return {
        "p25": round(percentile(values, 0.25)),
        "p50": round(percentile(values, 0.50)),
        "p75": round(percentile(values, 0.75)),
        "n": len(values),
        "sources": dict(sources),
    }


def pay_ranges(postings: list[dict], levels: list[dict]) -> dict:
    """{family: {"all": stats, seniority: stats}} from postings and Levels.fyi rows."""
    by_family = defaultdict(lambda: defaultdict(list))
    for p in postings:
        if p.get("pay_min") and p.get("pay_max") and (p.get("pay_currency") or "USD") == "USD":
            mid = (float(p["pay_min"]) + float(p["pay_max"])) / 2
            by_family[p["role_family"]][p["seniority"]].append((mid, "postings"))
    for r in levels:
        if r.get("base_usd"):
            by_family[r["role_family"]][r["seniority"]].append((float(r["base_usd"]), "levels"))
    out = {}
    for family, by_level in by_family.items():
        entry = {lvl: summarize(s) for lvl, s in by_level.items()}
        entry["all"] = summarize([x for s in by_level.values() for x in s])
        totals = sorted(float(r["total_usd"]) for r in levels if r["role_family"] == family and r.get("total_usd"))
        if totals:
            entry["all"]["total_comp_p50"] = round(percentile(totals, 0.5))
        out[family] = entry
    return out


# ---------------------------------------------------------------- competitiveness

def company_features(c: dict) -> dict:
    """Raw factor values for one company (None when unknown)."""
    open_roles = c.get("open_roles") or 0
    employees = None
    if c.get("employee_min"):
        employees = (c["employee_min"] + (c.get("employee_max") or c["employee_min"] * 2)) / 2
    return {
        "pay": c.get("median_pay"),
        "scarcity": (open_roles / employees * 100) if employees and open_roles else None,
        "scale": float(c["revenue_usd"]) if c.get("revenue_usd") else (float(c["funding_usd"]) if c.get("funding_usd") else None),
        "momentum": (c["new_roles_30d"] / open_roles) if open_roles >= 5 else None,
    }


def _rank(value: float, population: list[float]) -> float:
    """Fraction of the population strictly below value, ties counted half (0..1)."""
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return (below + 0.5 * equal) / len(population)


def competitiveness_scores(companies: dict[int, dict]) -> dict[int, dict | None]:
    feats = {cid: company_features(c) for cid, c in companies.items()}
    populations = {f: [x[f] for x in feats.values() if x[f] is not None] for f in WEIGHTS}
    out = {}
    for cid, f in feats.items():
        factors = {}
        for name, value in f.items():
            if value is None or len(populations[name]) < MIN_POPULATION:
                continue
            r = _rank(value, populations[name])
            # higher pay/scale => more competitive; more seats per employee or faster hiring => less
            factors[name] = r if name in ("pay", "scale") else 1 - r
        if len(factors) < 2:
            out[cid] = None
            continue
        total_w = sum(WEIGHTS[k] for k in factors)
        score = round(100 * sum(WEIGHTS[k] * v for k, v in factors.items()) / total_w)
        label = ("Very competitive" if score >= 75 else "Competitive" if score >= 55
                 else "Moderate" if score >= 35 else "Less competitive")
        out[cid] = {"score": score, "label": label, "factors": {k: round(v, 2) for k, v in factors.items()}}
    return out


# ---------------------------------------------------------------- interview difficulty

_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:or more\s+)?years?", re.IGNORECASE)
_ALGO = re.compile(r"algorithm|data structure|leetcode|coding (?:interview|challenge|assessment|exercise)|"
                   r"system design|competitive programming|problem[- ]solving", re.IGNORECASE)
_DEGREE = re.compile(r"\bph\.?d\b|\bdoctorate\b|master'?s degree|\bm\.?s\.? in\b", re.IGNORECASE)


def interview_signals(descriptions: list[str], seniorities: list[str]) -> dict:
    n = len(descriptions)
    years = []
    for d in descriptions:
        found = [int(m) for m in _YEARS.findall(d) if 0 < int(m) <= 20]
        if found:
            years.append(min(max(found), 15))
    senior = sum(1 for s in seniorities if s in ("senior", "staff_plus", "manager", "executive"))
    return {
        "postings": n,
        "avg_years_required": round(sum(years) / len(years), 1) if years else None,
        "algo_share": round(sum(1 for d in descriptions if _ALGO.search(d)) / n, 2) if n else 0,
        "degree_share": round(sum(1 for d in descriptions if _DEGREE.search(d)) / n, 2) if n else 0,
        "senior_share": round(senior / len(seniorities), 2) if seniorities else 0,
    }


def _label(score: float) -> str:
    return "Easy" if score < 2 else "Medium" if score < 3 else "Hard" if score < 4 else "Very hard"


def heuristic_difficulty(signals: dict, competitiveness: int | None) -> dict:
    score = 1.6
    years = signals["avg_years_required"]
    if years is not None:
        score += min(years, 10) * 0.15
    score += 0.7 * signals["algo_share"] + 0.5 * signals["degree_share"] + 0.3 * signals["senior_share"]
    if competitiveness is not None:
        score += 0.9 * competitiveness / 100
    score = round(max(1.0, min(5.0, score)), 1)
    bits = []
    if years is not None:
        bits.append(f"asks for ~{years:g} yrs experience on average")
    if signals["algo_share"] >= 0.3:
        bits.append(f"{round(signals['algo_share'] * 100)}% of postings mention algorithms/system design")
    if signals["degree_share"] >= 0.2:
        bits.append("advanced degrees often requested")
    if competitiveness is not None and competitiveness >= 70:
        bits.append("highly competitive employer")
    rationale = "; ".join(bits) or "few specific requirements in postings"
    return {"score": score, "label": _label(score), "rationale": rationale[0].upper() + rationale[1:],
            "signals": signals, "method": "heuristic"}


LLM_SYSTEM = ("You estimate how difficult a company's technical interview process is likely to be, using only the "
              "job requirements and signals provided. Reply with JSON: "
              '{"score": number 1-5 (one decimal), "rationale": string under 35 words, '
              '"focus_areas": up to 4 short strings (what interviews likely test)}.')


def llm_difficulty(llm, company: str, family: str, descriptions: list[str], signals: dict,
                   competitiveness: int | None) -> dict:
    excerpts = []
    for d in descriptions[:3]:
        m = re.search(r"(requirements|qualifications|what you.ll need|you have|about you)", d, re.IGNORECASE)
        excerpts.append(d[m.start():m.start() + 1500] if m else d[:1500])
    prompt = (f"Company: {company}\nRole family: {family.replace('_', ' ')}\n"
              f"Hiring competitiveness (0-100): {competitiveness if competitiveness is not None else 'unknown'}\n"
              f"Signals across {signals['postings']} postings: {signals}\n\n"
              + "\n\n---\n\n".join(excerpts))
    reply = llm(LLM_SYSTEM, prompt)
    score = round(max(1.0, min(5.0, float(reply["score"]))), 1)
    return {"score": score, "label": _label(score), "rationale": str(reply.get("rationale", ""))[:300],
            "focus_areas": [str(x) for x in reply.get("focus_areas", [])][:4], "signals": signals,
            "method": f"llm:{getattr(llm, 'model', 'unknown')}"}


# ---------------------------------------------------------------- orchestration

def compute_all(conn, llm=None, now: datetime | None = None, log=print) -> int:
    """Recompute company_insights for every company that has any data."""
    from lpp.db import save_insights

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    postings = defaultdict(list)
    for row in conn.execute(
            """SELECT company_id, role_family, seniority, pay_min, pay_max, pay_currency, description, first_seen
               FROM job_postings WHERE active"""):
        postings[row[0]].append({"role_family": row[1], "seniority": row[2], "pay_min": row[3], "pay_max": row[4],
                                 "pay_currency": row[5], "description": row[6] or "", "first_seen": row[7]})
    levels = defaultdict(list)
    for row in conn.execute("SELECT company_id, role_family, seniority, base_usd, total_usd FROM levels_comp"):
        levels[row[0]].append({"role_family": row[1], "seniority": row[2], "base_usd": row[3], "total_usd": row[4]})
    meta = {row[0]: {"name": row[1], "revenue_usd": row[2], "funding_usd": row[3], "employee_min": row[4],
                     "employee_max": row[5]}
            for row in conn.execute(
                """SELECT c.id, c.name, s.revenue_usd, f.total_usd, f.employee_min, f.employee_max
                   FROM companies c LEFT JOIN sec_financials s ON s.company_id = c.id
                   LEFT JOIN funding f ON f.company_id = c.id""")}

    with_data = set(postings) | set(levels) | {cid for cid, m in meta.items() if m["revenue_usd"] or m["funding_usd"]}
    base = {}
    for cid in with_data:
        ps = postings.get(cid, [])
        pay = pay_ranges(ps, levels.get(cid, []))
        mids = [s["all"]["p50"] for s in pay.values()]
        base[cid] = {
            **meta[cid],
            "pay": pay,
            "open_roles": len(ps),
            "new_roles_30d": sum(1 for p in ps if p["first_seen"] and p["first_seen"] >= cutoff),
            "median_pay": sorted(mids)[len(mids) // 2] if mids else None,
        }
    comp = competitiveness_scores(base)

    for cid, c in base.items():
        by_family = defaultdict(list)
        for p in postings.get(cid, []):
            by_family[p["role_family"]].append(p)
        interview = {}
        comp_score = comp[cid]["score"] if comp[cid] else None
        for family, ps in by_family.items():
            if family == "other":
                continue
            signals = interview_signals([p["description"] for p in ps], [p["seniority"] for p in ps])
            result = heuristic_difficulty(signals, comp_score)
            if llm is not None:
                try:
                    result = llm_difficulty(llm, c["name"], family, [p["description"] for p in ps], signals, comp_score)
                except Exception as exc:  # keep the heuristic if the LLM call fails
                    log(f"  LLM failed for {c['name']} / {family}: {exc}")
            interview[family] = result
        save_insights(conn, cid, {"open_roles": c["open_roles"], "new_roles_30d": c["new_roles_30d"],
                                  "pay": c["pay"], "competitiveness": comp[cid], "interview": interview})
    conn.commit()
    return len(base)
