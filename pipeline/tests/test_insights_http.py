import pytest

from lpp import insights
from lpp.http import HttpClient, NotFound


# ---------------------------------------------------------------- pay

def test_percentile_interpolates():
    assert insights.percentile([10, 20, 30, 40], 0.5) == 25
    assert insights.percentile([7], 0.9) == 7


def test_pay_ranges_pool_postings_and_levels():
    postings = [
        {"role_family": "software_engineering", "seniority": "mid", "pay_min": 140000, "pay_max": 160000, "pay_currency": "USD"},
        {"role_family": "software_engineering", "seniority": "senior", "pay_min": 200000, "pay_max": 240000, "pay_currency": "USD"},
        {"role_family": "software_engineering", "seniority": "mid", "pay_min": None, "pay_max": None},          # no pay: skipped
        {"role_family": "software_engineering", "seniority": "mid", "pay_min": 90000, "pay_max": 99000, "pay_currency": "EUR"},  # skipped
    ]
    levels = [{"role_family": "software_engineering", "seniority": "mid", "base_usd": 170000, "total_usd": 230000}]
    pay = insights.pay_ranges(postings, levels)["software_engineering"]
    assert pay["mid"]["n"] == 2 and pay["mid"]["p50"] == 160000
    assert pay["all"]["n"] == 3
    assert pay["all"]["sources"] == {"postings": 2, "levels": 1}
    assert pay["all"]["total_comp_p50"] == 230000


# ---------------------------------------------------------------- competitiveness

def _company(pay, revenue, open_roles, new, emp):
    return {"median_pay": pay, "revenue_usd": revenue, "open_roles": open_roles, "new_roles_30d": new,
            "employee_min": emp, "employee_max": emp}


def test_competitiveness_ranks_relative_to_population():
    companies = {
        1: _company(250000, 50e9, 40, 4, 10000),   # top pay, huge, few seats, slow hiring
        2: _company(200000, 5e9, 200, 60, 4000),
        3: _company(170000, 1e9, 150, 50, 1500),
        4: _company(150000, 3e8, 90, 45, 500),
        5: _company(120000, 5e7, 60, 40, 100),     # low pay, small, many seats, hiring fast
        6: {"median_pay": None, "revenue_usd": None, "open_roles": 0, "new_roles_30d": 0},  # no data
    }
    scores = insights.competitiveness_scores(companies)
    assert scores[1]["score"] > scores[3]["score"] > scores[5]["score"]
    assert scores[1]["label"] == "Very competitive"
    assert scores[5]["label"] == "Less competitive"
    assert set(scores[1]["factors"]) == {"pay", "scale", "scarcity", "momentum"}
    assert scores[6] is None


def test_competitiveness_needs_enough_population():
    few = {i: _company(100000 + i, 1e9, 10, 1, 100) for i in range(3)}
    assert all(v is None for v in insights.competitiveness_scores(few).values())


# ---------------------------------------------------------------- interview difficulty

DESCS = [
    "Requirements: 5+ years of experience. Strong algorithms and data structures. System design interview.",
    "3+ years building backend services. You'll do a coding interview.",
    "PhD or Master's degree in CS preferred. 7 years experience.",
    "Help customers.",
]


def test_interview_signals():
    s = insights.interview_signals(DESCS, ["senior", "mid", "staff_plus", "mid"])
    assert s["postings"] == 4
    assert s["avg_years_required"] == 5.0
    assert s["algo_share"] == 0.5
    assert s["degree_share"] == 0.25
    assert s["senior_share"] == 0.5


def test_heuristic_difficulty_orders_sensibly():
    hard = insights.heuristic_difficulty(insights.interview_signals(DESCS, ["senior"] * 4), 90)
    easy = insights.heuristic_difficulty(insights.interview_signals(["Help customers."] * 3, ["mid"] * 3), 20)
    assert 1 <= easy["score"] < hard["score"] <= 5
    assert hard["label"] in ("Hard", "Very hard")
    assert "algorithms" in hard["rationale"]
    assert hard["method"] == "heuristic"


def test_llm_difficulty_uses_reply_and_clamps():
    class FakeLLM:
        model = "fake-1"

        def __init__(self):
            self.prompts = []

        def __call__(self, system, prompt):
            self.prompts.append(prompt)
            return {"score": 9, "rationale": "LeetCode-heavy loop", "focus_areas": ["graphs", "system design"]}

    llm = FakeLLM()
    signals = insights.interview_signals(DESCS, ["mid"] * 4)
    r = insights.llm_difficulty(llm, "Ramp", "backend", DESCS, signals, 80)
    assert r["score"] == 5.0 and r["label"] == "Very hard"
    assert r["method"] == "llm:fake-1" and r["focus_areas"] == ["graphs", "system design"]
    assert "Requirements: 5+ years" in llm.prompts[0]   # requirement sections are what gets sent


# ---------------------------------------------------------------- HTTP client

class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        return self.responses.pop(0)


def test_http_retries_429_with_retry_after_then_succeeds():
    sleeps = []
    s = FakeSession([FakeResp(429, headers={"Retry-After": "3"}), FakeResp(503), FakeResp(200, {"ok": 1})])
    client = HttpClient("test ua", session=s, sleep=sleeps.append)
    assert client.get_json("https://example.com/x") == {"ok": 1}
    assert s.calls == 3
    assert 3.0 in sleeps and 2.0 in sleeps  # Retry-After honoured, then exponential backoff
    assert s.headers["User-Agent"] == "test ua"


def test_http_404_raises_not_found_and_gives_up_after_retries():
    client = HttpClient(session=FakeSession([FakeResp(404)]), sleep=lambda _: None)
    with pytest.raises(NotFound):
        client.get_json("https://example.com/missing")
    client = HttpClient(session=FakeSession([FakeResp(500)] * 5), max_retries=2, sleep=lambda _: None)
    with pytest.raises(RuntimeError):
        client.get_json("https://example.com/down")
