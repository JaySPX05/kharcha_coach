import json

import pandas as pd
import pytest

from core.insights import (compare_months, compute_insights, daily_spend, list_transactions, spend_by,
                           top_merchants)
from tests.conftest import _run

# Hand-checkable statement. Aug 1 2026 is a Saturday, Sep 1 2026 a Tuesday.
ROWS = [
    # date, amount, direction, counterparty, cp_type, category
    ("2026-08-01", 10000, "credit", "Person_01", "person", "Income"),
    ("2026-08-01", 300, "debit", "Swiggy", "merchant", "Food delivery"),
    ("2026-08-03", 20, "debit", "Chai", "merchant", "Eating out"),
    ("2026-08-04", 20, "debit", "Chai", "merchant", "Eating out"),
    ("2026-08-10", 119, "debit", "Spotify", "merchant", "Subscriptions"),
    ("2026-08-12", 500, "debit", "Person_02", "person", "Transfers to people"),
    ("2026-08-15", 900, "debit", "Myntra", "merchant", "Shopping"),
    ("2026-09-01", 10000, "credit", "Person_01", "person", "Income"),
    ("2026-09-05", 400, "debit", "Swiggy", "merchant", "Food delivery"),     # Sat
    ("2026-09-06", 200, "debit", "Swiggy", "merchant", "Food delivery"),     # Sun
    ("2026-09-07", 20, "debit", "Chai", "merchant", "Eating out"),
    ("2026-09-10", 119, "debit", "Spotify", "merchant", "Subscriptions"),
    ("2026-09-12", 3000, "debit", "Amazon", "merchant", "Shopping"),         # Sat
    ("2026-09-14", 500, "debit", "Myntra", "merchant", "Shopping"),
    ("2026-09-20", 150, "debit", "Person_02", "person", "Transfers to people"),  # Sun
]


@pytest.fixture
def df() -> pd.DataFrame:
    out = pd.DataFrame(ROWS, columns=["date", "amount", "direction", "counterparty", "cp_type", "category"])
    out["txn_id"] = [f"t{i:02d}" for i in range(len(out))]
    out["channel"] = "UPI"
    return out


def test_summary(df):
    ins = compute_insights(df)
    assert ins["month"] == "2026-09" and ins["months"] == ["2026-08", "2026-09"]
    # Sep spend: 400+200+20+119+3000+500+150 = 4389
    assert ins["summary"] == {"month": "2026-09", "income": 10000.0, "spend": 4389.0, "net": 5611.0,
                              "savings_rate": 56.11, "txn_count": 8}
    assert ins["monthly"][0]["spend"] == 1859.0  # Aug: 300+20+20+119+500+900


def test_daily_spend(df):
    days = daily_spend(df, "2026-09")
    assert len(days) == 30 and days[0] == {"date": "2026-09-01", "total": 0.0, "count": 0}  # credit only
    assert days[4] == {"date": "2026-09-05", "total": 400.0, "count": 1}
    assert sum(d["total"] for d in days) == 4389.0  # matches the month's spend
    json.dumps(days)


def test_by_category_and_top_merchants(df):
    ins = compute_insights(df, "2026-09")
    assert [(c["category"], c["total"], c["count"]) for c in ins["by_category"]] == [
        ("Shopping", 3500.0, 2), ("Food delivery", 600.0, 2), ("Transfers to people", 150.0, 1),
        ("Subscriptions", 119.0, 1), ("Eating out", 20.0, 1)]
    assert ins["by_category"][0]["share_pct"] == 79.74  # 3500 / 4389 = 0.79745
    assert [(m["merchant"], m["total"]) for m in ins["top_merchants"]] == [
        ("Amazon", 3000.0), ("Swiggy", 600.0), ("Myntra", 500.0), ("Spotify", 119.0), ("Chai", 20.0)]


def test_recurring_finds_spotify_only(df):
    # Swiggy varies, Chai is twice in Aug, Myntra 900 vs 500 isn't "similar"
    assert compute_insights(df)["recurring"] == [{"counterparty": "Spotify", "amount": 119.0,
                                                  "category": "Subscriptions", "months": 2,
                                                  "last_date": "2026-09-10"}]


def test_small_ticket_and_transfers(df):
    ins = compute_insights(df, "2026-09")
    assert ins["small_ticket"]["total"] == 289.0 and ins["small_ticket"]["count"] == 3  # 20+119+150
    assert ins["transfers_to_people"] == {"total": 150.0, "count": 1,
                                          "top": [{"counterparty": "Person_02", "total": 150.0, "count": 1}]}


def test_weekday_vs_weekend(df):
    # Sep 2026: 8 weekend days, 22 weekdays. Weekend 400+200+3000+150, weekday 20+119+500
    assert compute_insights(df, "2026-09")["weekday_vs_weekend"] == {
        "weekday_total": 639.0, "weekend_total": 3750.0, "weekday_per_day": 29.05, "weekend_per_day": 468.75}


def test_unusual(df):
    # Shopping median over all months = median(900, 3000, 500) = 900; 3000 > 3 x 900
    assert compute_insights(df, "2026-09")["unusual"] == [{
        "date": "2026-09-12", "counterparty": "Amazon", "category": "Shopping",
        "amount": 3000.0, "category_median": 900.0}]
    assert compute_insights(df, "2026-08")["unusual"] == []


def test_compare_months(df):
    c = compare_months(df, "2026-08", "2026-09")
    assert (c["spend_m1"], c["spend_m2"], c["change"], c["change_pct"]) == (1859.0, 4389.0, 2530.0, 136.09)
    assert [(r["category"], r["change"]) for r in c["by_category"]] == [
        ("Shopping", 2600.0), ("Transfers to people", -350.0), ("Food delivery", 300.0),
        ("Eating out", -20.0), ("Subscriptions", 0.0)]
    assert compute_insights(df)["category_change"]["by_category"] == c["by_category"]
    assert compute_insights(df, "2026-08")["category_change"] is None


def test_spend_by(df):
    assert spend_by(df, merchant="swiggy")["total"] == 900.0
    assert spend_by(df, merchant="Swiggy", month="2026-09") == {
        "merchant": "Swiggy", "category": None, "month": "2026-09", "total": 600.0, "count": 2}
    assert spend_by(df, category="food delivery", month="2026-08")["total"] == 300.0
    assert spend_by(df, merchant="nobody")["total"] == 0.0


def test_top_merchants_n(df):
    assert [m["merchant"] for m in top_merchants(df, n=2)] == ["Amazon", "Myntra"]  # 3000; 900+500


def test_list_transactions(df):
    rows = list_transactions(df, {"month": "2026-09", "category": "Shopping"})
    assert [(r["date"], r["counterparty"], r["amount"]) for r in rows] == [
        ("2026-09-14", "Myntra", 500.0), ("2026-09-12", "Amazon", 3000.0)]
    assert len(list_transactions(df, {"min_amount": 1000})) == 3
    assert len(list_transactions(df, {"direction": "debit"}, limit=4)) == 4
    with pytest.raises(ValueError, match="Unknown filters"):
        list_transactions(df, {"shop": "x"})


def test_recurring_person_needs_three_months(df):
    extra = pd.DataFrame([("2026-07-12", 500, "debit", "Person_02", "person", "Transfers to people")],
                         columns=["date", "amount", "direction", "counterparty", "cp_type", "category"])
    df2 = pd.concat([df.drop(index=14), extra], ignore_index=True)  # 500 on Jul 12, Aug 12 only
    df2["txn_id"], df2["channel"] = [f"t{i}" for i in range(len(df2))], "UPI"
    assert [r["counterparty"] for r in compute_insights(df2)["recurring"]] == ["Spotify"]


def test_bad_month(df):
    with pytest.raises(ValueError, match="YYYY-MM"):
        spend_by(df, month="Sep 2026")
    with pytest.raises(ValueError, match="Available months"):
        compute_insights(df, "2026-01")


def test_missing_category_counts_as_other(df):
    df["category"] = None
    assert compute_insights(df)["by_category"][0]["category"] == "Other"


# ---------- full synthetic statement ----------

CATEGORY_OF = {
    "Swiggy": "Food delivery", "Zomato": "Food delivery", "Zepto": "Groceries", "Blinkit": "Groceries",
    "Rapido": "Transport", "Namma Metro": "Transport", "Amazon": "Shopping", "Myntra": "Shopping",
    "Spotify": "Subscriptions", "Netflix": "Subscriptions", "Jio Recharge": "Bills & recharge", "ATM": "Cash withdrawal",
}


@pytest.fixture(scope="module")
def synthetic() -> pd.DataFrame:
    """Redacted sample with stand-in categories (the real ones come from the teammate's LLM step)."""
    *_, red = _run("statement", "csv")
    red = red.copy()
    red["category"] = red["counterparty"].map(CATEGORY_OF)
    red.loc[red["cp_type"] == "person", "category"] = "Transfers to people"
    red.loc[red["direction"] == "credit", "category"] = "Income"
    return red.fillna({"category": "Eating out"})


@pytest.mark.parametrize("month", ["2026-07", "2026-08", "2026-09"])
def test_synthetic_insights_are_json_safe(synthetic, month):
    ins = compute_insights(synthetic, month)
    json.dumps(ins, allow_nan=False)
    assert ins["summary"]["spend"] > 0 and ins["by_category"] and ins["top_merchants"]


def test_synthetic_patterns_are_found(synthetic):
    ins = compute_insights(synthetic, "2026-09")
    recurring = {r["counterparty"]: r["amount"] for r in ins["recurring"]}
    assert {"Spotify": 119.0, "Netflix": 199.0, "Jio Recharge": 299.0}.items() <= recurring.items()
    assert 6000.0 in recurring.values()  # rent to the landlord's alias
    assert "ATM" not in recurring and len(recurring) == 4  # no chance P2P repeats or cash
    assert all(u["amount"] != 6000.0 for u in ins["unusual"])  # rent is expected, not unusual
    assert any(u["counterparty"] == "Amazon" and u["amount"] == 4999.0 for u in ins["unusual"])
    assert ins["small_ticket"]["count"] > 50  # lots of chai
    totals = [m["spend"] for m in ins["monthly"]]
    assert totals == sorted(totals)  # spend rises Jul -> Sep


def test_helpers_are_json_safe(synthetic):
    for out in (spend_by(synthetic, merchant="swiggy"), top_merchants(synthetic),
                compare_months(synthetic, "2026-07", "2026-09"),
                list_transactions(synthetic, {"merchant": "zomato"}, limit=5)):
        json.dumps(out, allow_nan=False)
