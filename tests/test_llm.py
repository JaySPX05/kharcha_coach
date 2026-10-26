"""Tests for llm/ using a fake client — no API key, no network."""
import threading
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.pipeline import run_pipeline
from core.insights import compute_insights
from core.schema import validate
from llm import client
from llm.categorize import categorize, load_cache
from llm.categories import normalise_merchant, rule_category
from llm.chat import answer
from llm.coach import coach_report
from llm.tools import run_tool, txn_count
from llm.verify import format_inr, unverified_numbers
from tests.fake_llm import FakeClient

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "statement.csv"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeClient()
    client.set_client(f)
    client.reset_log()
    monkeypatch.setattr("llm.categorize.CACHE_PATH", tmp_path / "cache.json")
    yield f
    client.set_client(None)


@pytest.fixture
def pipeline(fake, tmp_path):
    df = run_pipeline(SAMPLE.read_bytes(), "statement.csv")
    return SimpleNamespace(df=df, insights=compute_insights(df))


# ---------- client
def test_strip_reasoning():
    assert client.strip_reasoning("<think>hmm 2+2</think>\n{\"a\": 1}") == '{"a": 1}'
    assert client.strip_reasoning("hmm</think> answer") == "answer"


def test_chat_logs_usage_and_sets_thinking(fake):
    client.chat("nano", [{"role": "user", "content": "hi"}], purpose="t")
    assert client.CALL_LOG[-1].tier == "nano" and client.CALL_LOG[-1].cost_usd > 0
    assert fake.requests[-1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    client.chat("ultra", [{"role": "user", "content": "hi"}])
    assert fake.requests[-1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_collect_calls_keeps_concurrent_visitors_apart(fake):
    """Two visitors' requests overlapping in time (Streamlit threads) must not see each other's calls."""
    a_called, b_done, got = threading.Event(), threading.Event(), {}

    def visitor_a():
        client.chat("nano", [{"role": "user", "content": "a"}])
        a_called.set()
        b_done.wait(5)  # visitor B's call lands while A's request is still running

    def visitor_b():
        a_called.wait(5)
        got["b"] = client.collect_calls(client.chat, "ultra", [{"role": "user", "content": "b"}])[1]
        b_done.set()

    tb = threading.Thread(target=visitor_b)
    tb.start()
    got["a"] = client.collect_calls(visitor_a)[1]
    tb.join(5)
    assert [c.tier for c in got["a"]] == ["nano"] and [c.tier for c in got["b"]] == ["ultra"]
    assert client.CALL_LOG == []  # the app's calls never pile up in the process-wide log


def test_retry_on_429(fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    real = fake.chat.completions.create
    calls = {"n": 0}

    class RateLimited(Exception):
        status_code = 429

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("slow down")
        return real(**kw)
    fake.chat.completions.create = flaky
    assert client.chat("super", [{"role": "user", "content": "x"}]).content == "ok"
    assert calls["n"] == 2


# ---------- rules + categoriser
@pytest.mark.parametrize("name,vpa,cat", [
    ("College Canteen", None, "Eating out"),
    ("Swiggy Instamart", "instamart@icici", "Groceries"),
    ("Swiggy", "swiggy@ybl", "Food delivery"),
    ("Coca Cola Store", None, None),          # 'ola' must not match inside 'cola'
    ("Steam Games", None, "Entertainment"),   # 'tea' must not match inside 'steam'
])
def test_rules(name, vpa, cat):
    assert rule_category(name, vpa) == cat


def test_normalise():
    assert normalise_merchant("SWIGGY Pvt. Ltd") == normalise_merchant("swiggy") == "swiggy"


def test_categorize_people_credits_atm_without_model(fake):
    df = pd.DataFrame([
        {"counterparty": "Person_01", "vpa": "person_01@ybl", "cp_type": "person", "direction": "debit", "channel": "UPI"},
        {"counterparty": "Person_02", "vpa": None, "cp_type": "person", "direction": "credit", "channel": "NEFT"},
        {"counterparty": "ATM", "vpa": None, "cp_type": "unknown", "direction": "debit", "channel": "ATM"},
    ])
    out = categorize(df)
    assert list(out["category"]) == ["Transfers to people", "Income", "Cash withdrawal"]
    assert fake.requests == []


def test_person_remark_rent(fake):
    df = pd.DataFrame([{"counterparty": "Person_05", "vpa": "person_05@ybl", "cp_type": "person",
                        "direction": "debit", "channel": "UPI",
                        "narration": "UPI/DR/XXXXXXXX8667/Person_05/SBIN/person_05@ybl/rent"},
                       {"counterparty": "Person_06", "vpa": "person_06@ybl", "cp_type": "person",
                        "direction": "debit", "channel": "UPI",
                        "narration": "UPI/DR/XXXXXXXX8668/Person_06/SBIN/person_06@ybl/Payment"}])
    assert list(categorize(df)["category"]) == ["Rent", "Transfers to people"]


def test_categorize_batches_and_caches(fake):
    names = [f"Unique Shop {i}" for i in range(45)]
    df = pd.DataFrame({"counterparty": names * 2, "vpa": None, "cp_type": "merchant",
                       "direction": "debit", "channel": "UPI"})
    out = categorize(df)
    assert len(fake.requests) == 2                       # 45 unique -> batches of 40 + 5
    assert set(out["category_source"]) == {"llm"}
    again = categorize(df)
    assert len(fake.requests) == 2 and set(again["category_source"]) == {"cache"}


def test_invalid_category_retries_then_other(fake):
    fake.category_for = lambda n: "Snacks"               # not in the list
    df = pd.DataFrame({"counterparty": ["Weird Place"], "vpa": None, "cp_type": "merchant",
                       "direction": "debit", "channel": "UPI"})
    out = categorize(df)
    assert out["category"].iloc[0] == "Other" and len(fake.requests) == 2


def test_aliases_never_reach_nano_or_cache(fake):
    # cp_type "unknown" but aliased by redact(): Person_01 means someone else in the next statement
    df = pd.DataFrame({"counterparty": ["Person_01"], "vpa": "person_01@oksbi", "cp_type": "unknown",
                       "direction": "debit", "channel": "UPI", "narration": "UPI/DR/XXXXXXXX8901/Person_01/x"})
    out = categorize(df)
    assert out["category"].iloc[0] == "Other"  # not "Transfers to people": unknown may be a shop
    assert fake.requests == [] and load_cache() == {}


def test_pipeline_output_passes_schema(pipeline):
    validate(pipeline.df)
    assert pipeline.df["category"].notna().all()


def test_nano_never_sees_pii(pipeline, fake):
    sent = "\n".join(str(m["content"]) for r in fake.requests for m in r["messages"])
    import re
    assert not re.search(r"\d{10}", sent)               # no phone / account / UPI ref
    assert "UPI/DR" not in sent                         # no raw narrations


# ---------- tools + chat
def test_tool_errors_go_back_to_model(pipeline):
    assert "error" in run_tool("spend_by", {"month": "Sept"}, pipeline.df)
    assert "error" in run_tool("nope", {}, pipeline.df)
    assert "error" in run_tool("spend_by", "{bad json", pipeline.df)


def test_chat_uses_tool_and_quotes_its_number(pipeline):
    r = answer("How much did I spend on Swiggy in September?", pipeline.df, [])
    from core.insights import spend_by
    expected = spend_by(pipeline.df, "swiggy", None, "2026-09")
    assert r["tool_calls"][0]["name"] == "spend_by"
    assert f"{expected['total']:,.0f}" in r["text"]
    assert r["txn_count"] == expected["count"] and r["unverified"] == []


def test_chat_survives_broken_tool_arguments(pipeline, fake, monkeypatch):
    """A half-written tool call must go back to the model as an error, and each call keeps its own result."""
    real = fake.chat.completions.create
    good = SimpleNamespace(id="good", function=SimpleNamespace(name="spend_by", arguments='{"merchant": "swiggy"}'))
    bad = SimpleNamespace(id="bad", function=SimpleNamespace(name="spend_by", arguments='{"month": "2026-09"'))

    def create(**kw):
        if not any(m.get("role") == "tool" for m in kw["messages"]):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[bad, good]))],
                                   usage=None)
        return real(**kw)

    monkeypatch.setattr(fake.chat.completions, "create", create)
    r = answer("How much on Swiggy?", pipeline.df, [])
    assert "error" in r["tool_calls"][0]["result"]
    assert r["tool_calls"][1]["result"]["total"] == run_tool("spend_by", {"merchant": "swiggy"}, pipeline.df)["result"]["total"]


def test_chat_flags_invented_number(pipeline, fake):
    fake.chat_invent = True
    r = answer("How much on Swiggy?", pipeline.df, [])
    assert "12,345" in r["unverified"]


# ---------- coach
def test_coach_report_valid_and_traceable(pipeline):
    rep = coach_report(pipeline.insights, "Save Rs 5,000 for a trip")
    assert len(rep["actions"]) == 3 and rep["summary"]
    actual = {c["category"]: c["total"] for c in pipeline.insights["by_category"]}
    assert all(b["last_month"] == actual[b["category"]] for b in rep["budgets"])
    assert rep["unverified"] == []


def test_coach_flags_invented_figure(pipeline, fake):
    fake.coach_invent = True
    assert "98,765" in coach_report(pipeline.insights)["unverified"]


def test_coach_never_sees_transactions(pipeline, fake):
    coach_report(pipeline.insights)
    sent = fake.requests[-1]["messages"][0]["content"]
    assert "UPI/" not in sent and "txn_id" not in sent


# ---------- verify / formatting
def test_format_inr():
    assert format_inr(1234567.8) == "12,34,568"
    assert format_inr(999) == "999" and format_inr(-45000) == "-45,000"


def test_unverified_allows_sums_rounding_and_small_counts():
    src = {"a": 3007.0, "b": 5999.0}
    assert unverified_numbers("Rs 3,007 to Rs 5,999, up Rs 2,992 across 18 orders in 2026", src) == []
    assert unverified_numbers("about Rs 4,100", src) == ["4,100"]


# ---------- extra chat tools (added after live run: Q7 and Q8 failed without them)
def test_largest_transactions_sorted_by_amount(pipeline):
    rows = run_tool("largest_transactions", {"month": "2026-09", "n": 3}, pipeline.df)["result"]
    amounts = [r["amount"] for r in rows]
    assert len(rows) == 3 and amounts == sorted(amounts, reverse=True)
    assert amounts[0] == pipeline.df.loc[pipeline.df["direction"] == "debit", "amount"][
        pipeline.df["date"].astype(str).str.startswith("2026-09")].max()


def test_sum_transactions_matches_small_ticket_insight(pipeline):
    res = run_tool("sum_transactions", {"month": "2026-09", "max_amount": 199.99}, pipeline.df)["result"]
    st = pipeline.insights["small_ticket"]
    assert (res["total"], res["count"]) == (st["total"], st["count"])


def test_recurring_tool_includes_all_subscriptions(pipeline):
    names = {r["counterparty"] for r in run_tool("recurring_payments", {}, pipeline.df)["result"]}
    assert {"Netflix", "Spotify", "Jio Recharge"} <= names


def test_txn_count_is_never_zero_for_a_real_list(pipeline):
    rec = run_tool("recurring_payments", {}, pipeline.df)["result"]
    assert txn_count("recurring_payments", rec) == len(rec) > 0
    assert txn_count("compare_months", {}) == 0  # the app hides the caption's count when it is 0


def test_retry_on_529_overloaded(fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    real = fake.chat.completions.create
    calls = {"n": 0}

    class Overloaded(Exception):
        status_code = 529

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise Overloaded("System is overloaded")
        return real(**kw)
    fake.chat.completions.create = flaky
    assert client.chat("super", [{"role": "user", "content": "x"}]).content == "ok"
    assert calls["n"] == 3


def test_unverified_pairs_only_from_numbers_quoted_in_text():
    src = {"a": 8048.0, "b": 12072.0}
    # 4,024 is b - a, but the text doesn't quote a and b, so it's an invented figure
    assert unverified_numbers("trim it by half and save Rs 4,024", src) == ["4,024"]
    assert unverified_numbers("Rs 8,048 vs Rs 12,072, a gap of Rs 4,024", src) == []
    assert unverified_numbers("about Rs 8,000", src) == ["8,000"]   # rounding to a new figure


@pytest.mark.parametrize("q,expected", [
    ("kitna paisa doston ko bheja?", True), ("Mera savings rate kya hai?", True),
    ("Compare August and September", False), ("How much did I spend on Swiggy?", False),
])
def test_hinglish_detection(q, expected):
    from llm.chat import is_hinglish
    assert is_hinglish(q) is expected


def test_tool_results_say_which_period(pipeline):
    assert run_tool("spend_by", {"merchant": "swiggy"}, pipeline.df)["period"].startswith("ALL months")
    assert run_tool("spend_by", {"merchant": "swiggy", "month": "2026-09"}, pipeline.df)["period"] == "2026-09"


def test_person_filter_not_offered_to_model():
    from llm.tools import TOOL_SCHEMAS
    assert "cp_type" not in str(TOOL_SCHEMAS)   # 'person' includes rent; friends = Transfers to people
