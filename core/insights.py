"""All the maths. Models never compute numbers; they quote what these functions return.

Every public function returns JSON-safe values (plain float/int/str/None, no numpy, no Timestamps).
"""

import re

import pandas as pd

SMALL_TICKET = 200.0
UNUSUAL_FACTOR = 3.0
RECURRING_TOLERANCE = 0.10  # amount within ±10% of the usual amount
RECURRING_GAP_DAYS = (20, 40)  # "about monthly"
RECURRING_MIN_MONTHS = {"merchant": 2, "person": 3}  # equal P2P amounts twice is often chance
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
LIST_FILTERS = ("month", "merchant", "category", "direction", "channel", "cp_type", "min_amount", "max_amount")


def _num(x: float) -> float:
    return round(float(x), 2)


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_date"] = pd.to_datetime(out["date"])
    out["_month"] = out["_date"].dt.strftime("%Y-%m")
    out["category"] = out["category"].fillna("Other")  # uncategorised rows still count
    out["amount"] = out["amount"].astype(float)
    return out


def _check_month(month: str | None) -> None:
    if month is not None and not MONTH_RE.match(str(month)):
        raise ValueError(f"month must look like 'YYYY-MM', got {month!r}")


def _debits(d: pd.DataFrame, month: str | None = None) -> pd.DataFrame:
    out = d[d["direction"] == "debit"]
    return out if month is None else out[out["_month"] == month]


def _totals(rows: pd.DataFrame, key: str, label: str) -> list[dict]:
    """Group by `key`, sum and count amounts, biggest first."""
    g = rows.groupby(key)["amount"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    return [{label: str(k), "total": _num(r["sum"]), "count": int(r["count"])} for k, r in g.iterrows()]


# ---------- the dashboard / coach payload ----------

def compute_insights(df: pd.DataFrame, month: str | None = None) -> dict:
    """Everything the dashboard and coach report need. `month` defaults to the latest month."""
    _check_month(month)
    d = _prep(df)
    months = sorted(d["_month"].unique().tolist())
    if not months:
        raise ValueError("No transactions to analyse.")
    month = month or months[-1]
    if month not in months:
        raise ValueError(f"No transactions in {month}. Available months: {months}")
    prev = months[months.index(month) - 1] if months.index(month) > 0 else None
    spend = _debits(d, month)
    monthly = _monthly(d)
    recurring = _recurring(d)

    return {
        "month": month,
        "months": months,
        "monthly": monthly,
        "summary": next(m for m in monthly if m["month"] == month),
        "by_category": _by_category(spend),
        "top_merchants": top_merchants(df, n=10, month=month),
        "recurring": recurring,
        "small_ticket": _small_ticket(spend),
        "transfers_to_people": _transfers(spend),
        "late_night": {"available": False, "reason": "statement has dates only, no times"},
        "weekday_vs_weekend": _weekday_weekend(spend, month),
        "category_change": _category_change(d, prev, month) if prev else None,
        "unusual": _unusual(d, month, recurring),
    }


def _monthly(d: pd.DataFrame) -> list[dict]:
    out = []
    for m, g in d.groupby("_month"):
        income = g.loc[g["direction"] == "credit", "amount"].sum()
        spend = g.loc[g["direction"] == "debit", "amount"].sum()
        out.append({
            "month": m, "income": _num(income), "spend": _num(spend), "net": _num(income - spend),
            "savings_rate": _num((income - spend) / income * 100) if income > 0 else None,  # percent
            "txn_count": int(len(g)),
        })
    return out


def _by_category(spend: pd.DataFrame) -> list[dict]:
    total = spend["amount"].sum()
    rows = _totals(spend, "category", "category")
    for r in rows:
        r["share_pct"] = _num(r["total"] / total * 100) if total else 0.0
    return rows


def _recurring(d: pd.DataFrame) -> list[dict]:
    """Same counterparty, similar amount, once a month, about a month apart, in 2+ months."""
    out = []
    debits = _debits(d)
    for cp, g in debits[debits["channel"] != "ATM"].groupby("counterparty"):
        usual = g["amount"].median()
        hits = g[(g["amount"] - usual).abs() <= RECURRING_TOLERANCE * usual].sort_values("_date")
        months = hits["_month"].nunique()
        min_months = RECURRING_MIN_MONTHS.get(str(g["cp_type"].iloc[0]), 3)
        if months < min_months or len(hits) != months:  # need exactly one matching payment per month
            continue
        gaps = hits["_date"].diff().dt.days.dropna()
        if not gaps.between(*RECURRING_GAP_DAYS).all():
            continue
        out.append({
            "counterparty": str(cp), "amount": _num(hits["amount"].median()),
            "category": str(hits["category"].mode().iloc[0]), "months": int(months),
            "last_date": hits["_date"].iloc[-1].strftime("%Y-%m-%d"),
        })
    return sorted(out, key=lambda r: -r["amount"])


def _small_ticket(spend: pd.DataFrame) -> dict:
    small = spend[spend["amount"] < SMALL_TICKET]
    return {"threshold": SMALL_TICKET, "total": _num(small["amount"].sum()), "count": int(len(small)),
            "by_category": _totals(small, "category", "category")}


def _transfers(spend: pd.DataFrame) -> dict:
    people = spend[spend["cp_type"] == "person"]
    return {"total": _num(people["amount"].sum()), "count": int(len(people)),
            "top": _totals(people, "counterparty", "counterparty")[:5]}


def _weekday_weekend(spend: pd.DataFrame, month: str) -> dict:
    days = pd.date_range(f"{month}-01", periods=pd.Period(month).days_in_month)
    n_weekend = int((days.day_of_week >= 5).sum())
    weekend = spend["_date"].dt.day_of_week >= 5
    wk_total, we_total = spend.loc[~weekend, "amount"].sum(), spend.loc[weekend, "amount"].sum()
    return {
        "weekday_total": _num(wk_total), "weekend_total": _num(we_total),
        "weekday_per_day": _num(wk_total / (len(days) - n_weekend)),
        "weekend_per_day": _num(we_total / n_weekend),
    }


def _category_change(d: pd.DataFrame, prev: str, month: str) -> dict:
    return {"from": prev, "to": month, "by_category": _compare_by_category(d, prev, month)}


def _unusual(d: pd.DataFrame, month: str, recurring: list[dict]) -> list[dict]:
    """Debits in `month` above 3x the median for their category (median over all months).

    Known recurring payments (rent, subscriptions) are expected, so never unusual.
    """
    debits = _debits(d)
    median = debits.groupby("category")["amount"].transform("median")
    expected = pd.Series(False, index=debits.index)
    for r in recurring:
        expected |= (debits["counterparty"] == r["counterparty"]) & (
            (debits["amount"] - r["amount"]).abs() <= RECURRING_TOLERANCE * r["amount"])
    hits = debits[(debits["_month"] == month) & (debits["amount"] > UNUSUAL_FACTOR * median) & ~expected]
    return [{
        "date": r["_date"].strftime("%Y-%m-%d"), "counterparty": str(r["counterparty"]),
        "category": str(r["category"]), "amount": _num(r["amount"]),
        "category_median": _num(median[i]),
    } for i, r in hits.sort_values("amount", ascending=False).iterrows()]


# ---------- query helpers (teammate wraps these as model tools) ----------

def spend_by(df: pd.DataFrame, merchant: str | None = None, category: str | None = None,
             month: str | None = None) -> dict:
    """Total debits, optionally filtered. `merchant` is a case-insensitive substring of counterparty."""
    _check_month(month)
    rows = _filter(_debits(_prep(df), month), merchant=merchant, category=category)
    return {"merchant": merchant, "category": category, "month": month,
            "total": _num(rows["amount"].sum()), "count": int(len(rows))}


def top_merchants(df: pd.DataFrame, n: int = 10, month: str | None = None) -> list[dict]:
    """Merchants (not people) ranked by total spend."""
    _check_month(month)
    spend = _debits(_prep(df), month)
    return _totals(spend[spend["cp_type"] == "merchant"], "counterparty", "merchant")[:n]


def compare_months(df: pd.DataFrame, m1: str, m2: str) -> dict:
    """Spend in m1 vs m2, overall and per category. change = m2 - m1."""
    _check_month(m1)
    _check_month(m2)
    d = _prep(df)
    s1, s2 = _debits(d, m1)["amount"].sum(), _debits(d, m2)["amount"].sum()
    return {"m1": m1, "m2": m2, "spend_m1": _num(s1), "spend_m2": _num(s2), "change": _num(s2 - s1),
            "change_pct": _num((s2 - s1) / s1 * 100) if s1 else None,
            "by_category": _compare_by_category(d, m1, m2)}


def _compare_by_category(d: pd.DataFrame, m1: str, m2: str) -> list[dict]:
    """Per-category spend for two months of an already-prepped frame; biggest change first."""
    a = _debits(d, m1).groupby("category")["amount"].sum()
    b = _debits(d, m2).groupby("category")["amount"].sum()
    both = pd.concat([a.rename("m1"), b.rename("m2")], axis=1).fillna(0.0)
    both["change"] = both["m2"] - both["m1"]
    both = both.reindex(both["change"].abs().sort_values(ascending=False).index)
    return [{"category": str(c), "m1": _num(r["m1"]), "m2": _num(r["m2"]), "change": _num(r["change"]),
             "change_pct": _num(r["change"] / r["m1"] * 100) if r["m1"] else None}
            for c, r in both.iterrows()]


def list_transactions(df: pd.DataFrame, filters: dict, limit: int = 20) -> list[dict]:
    """Matching transactions, newest first. Filter keys: see LIST_FILTERS."""
    unknown = set(filters) - set(LIST_FILTERS)
    if unknown:
        raise ValueError(f"Unknown filters {sorted(unknown)}; allowed: {list(LIST_FILTERS)}")
    _check_month(filters.get("month"))
    d = _prep(df)
    if filters.get("month"):
        d = d[d["_month"] == filters["month"]]
    d = _filter(d, merchant=filters.get("merchant"), category=filters.get("category"))
    for col in ("direction", "channel", "cp_type"):
        if filters.get(col):
            d = d[d[col] == filters[col]]
    if filters.get("min_amount") is not None:
        d = d[d["amount"] >= float(filters["min_amount"])]
    if filters.get("max_amount") is not None:
        d = d[d["amount"] <= float(filters["max_amount"])]
    d = d.sort_values("_date", ascending=False, kind="stable").head(max(0, int(limit)))
    return [{"txn_id": str(r["txn_id"]), "date": r["_date"].strftime("%Y-%m-%d"),
             "counterparty": str(r["counterparty"]), "amount": _num(r["amount"]),
             "direction": str(r["direction"]), "category": str(r["category"]), "channel": str(r["channel"])}
            for _, r in d.iterrows()]


def _filter(d: pd.DataFrame, merchant: str | None = None, category: str | None = None) -> pd.DataFrame:
    if merchant:
        d = d[d["counterparty"].astype(str).str.contains(merchant, case=False, regex=False)]
    if category:
        d = d[d["category"].str.lower() == category.lower()]
    return d
